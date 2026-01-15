from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, List

from django.utils import timezone

from orchestration.models import SoftEvent, SoftEventSlot, Chat
from orchestration.registry import register_function
from orchestration.services import SoftEventService
from orchestration.soft_scheduler import collect_window_state
from orchestration.soft_planner import plan_soft_window
from orchestration.tools.calendar import list_events


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val)
    except Exception:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone=timezone.utc)
    return dt


@register_function(
    manifest_id="soft_events.create_soft_event",
    module="soft_events",
    name="soft_events.create_soft_event",
    description="Create a flexible soft event (task) that can be scheduled by Corv.",
    params_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "notes": {"type": "string", "description": "Optional scheduling notes"},
            "duration_minutes": {"type": "integer", "default": 30},
            "soft_deadline": {"type": "string", "description": "ISO datetime deadline (soft)"},
            "hard_deadline": {"type": "string", "description": "ISO datetime deadline (hard)"},
            "frequency": {"type": "string", "description": "Optional recurrence description (e.g., weekly)"},
            "preferred_dayparts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Hints like morning/afternoon/evening",
            },
            "deferral_limit": {"type": "integer", "default": 3},
            "priority": {"type": "integer", "default": 0, "description": "Higher = more urgent"},
            "chat_id": {"type": "string", "description": "Optional chat id for context/notifications"},
        },
        "required": ["title"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "status": {"type": "string"},
        },
    },
)
def create_soft_event(
    title: str,
    description: str = "",
    notes: str = "",
    duration_minutes: int = 30,
    soft_deadline: Optional[str] = None,
    hard_deadline: Optional[str] = None,
    frequency: str = "",
    preferred_dayparts: Optional[List[str]] = None,
    deferral_limit: int = 3,
    priority: int = 0,
    chat_id: Optional[str] = None,
):
    chat = None
    if chat_id:
        try:
            chat = Chat.objects.get(id=chat_id)
        except Chat.DoesNotExist:
            chat = None

    se = SoftEvent.objects.create(
        title=title,
        description=description or "",
        notes=notes or "",
        duration_minutes=max(duration_minutes or 0, 1),
        soft_deadline=_parse_dt(soft_deadline),
        hard_deadline=_parse_dt(hard_deadline),
        frequency=frequency or "",
        preferred_dayparts=preferred_dayparts or [],
        deferral_limit=max(deferral_limit or 0, 0),
        priority=priority or 0,
        chat=chat,
        status=SoftEvent.STATUS_ACTIVE,
    )
    return {"id": str(se.id), "title": se.title, "status": se.status}


@register_function(
    manifest_id="soft_events.list_soft_events",
    module="soft_events",
    name="soft_events.list_soft_events",
    description="List soft events, optionally filtering by event status, slot status, and time window.",
    params_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by status (active/paused/archived)"},
            "slot_status": {"type": "string", "description": "Optional slot status filter (planned, completed, etc.)"},
            "time_min": {"type": "string", "description": "ISO lower bound to filter slots"},
            "time_max": {"type": "string", "description": "ISO upper bound to filter slots"},
        },
    },
)
def list_soft_events(
    status: Optional[str] = None,
    slot_status: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
):
    qs = SoftEvent.objects.all().order_by("-created_at")
    if status:
        qs = qs.filter(status=status)

    slot_map = {}
    slot_filters = {}
    if slot_status:
        slot_filters["status"] = slot_status
    if time_min:
        slot_filters["start_at__gte"] = _parse_dt(time_min)
    if time_max:
        slot_filters["end_at__lte"] = _parse_dt(time_max)
    if slot_filters:
        slots = SoftEventSlot.objects.select_related("soft_event").filter(**slot_filters)
        for slot in slots:
            slot_map.setdefault(slot.soft_event_id, []).append(slot)
        qs = qs.filter(id__in=slot_map.keys())

    out = []
    for se in qs:
        event_slots = slot_map.get(se.id, [])
        slot_payload = [
            {
                "id": str(sl.id),
                "start_at": sl.start_at.isoformat(),
                "end_at": sl.end_at.isoformat(),
                "status": sl.status,
                "deferral_count": sl.deferral_count,
                "rationale": sl.rationale,
            }
            for sl in event_slots
        ]
        out.append(
            {
                "id": str(se.id),
                "title": se.title,
                "description": se.description,
                "notes": se.notes,
                "status": se.status,
                "priority": se.priority,
                "duration_minutes": se.duration_minutes,
                "soft_deadline": se.soft_deadline.isoformat() if se.soft_deadline else None,
                "hard_deadline": se.hard_deadline.isoformat() if se.hard_deadline else None,
                "slots": slot_payload,
            }
        )
    return {"events": out}


@register_function(
    manifest_id="soft_events.promote_slot",
    module="soft_events",
    name="soft_events.promote_slot",
    description="Promote a planned soft event slot to a hard calendar event.",
    params_schema={
        "type": "object",
        "properties": {
            "slot_id": {"type": "string"},
            "summary": {"type": "string", "description": "Optional override title"},
            "description": {"type": "string", "description": "Optional description"},
            "calendar_id": {"type": "string", "description": "Target calendar id"},
            "timezone": {"type": "string", "description": "IANA timezone"},
        },
        "required": ["slot_id"],
    },
)
def promote_slot(
    slot_id: str,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    calendar_id: Optional[str] = None,
    timezone_name: Optional[str] = None,
):
    actions = [
        {
            "type": "promote_slot",
            "slot_id": slot_id,
            "summary": summary,
            "description": description,
            "calendar_id": calendar_id,
            "timezone": timezone_name,
        }
    ]
    created, updated = SoftEventService.apply_planner_actions(actions, planner_trace_id="manual-promote")
    return {"updated": updated}


@register_function(
    manifest_id="soft_events.replan_window",
    module="soft_events",
    name="soft_events.replan_window",
    description="Manually trigger a replan of the next N days with an optional note.",
    params_schema={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 14},
            "note": {"type": "string", "description": "Optional guidance for the planner (e.g., keep today free)."},
        },
    },
)
def replan_window(days: int = 14, note: Optional[str] = None):
    now = timezone.now()
    window_start = now
    window_end = now + timedelta(days=max(days or 1, 1))

    hard_resp = list_events(
        time_min=window_start.isoformat(),
        time_max=window_end.isoformat(),
        max_results=2500,
    )
    hard_events = hard_resp.get("events", [])
    soft_state = collect_window_state(window_start, window_end)

    if note:
        # Add a planner note as a pseudo event to steer scheduling.
        hard_events = [
            {
                "id": "note",
                "summary": f"Planner note: {note}",
                "start": window_start.isoformat(),
                "end": window_start.isoformat(),
            }
        ] + hard_events

    actions, trace_id = plan_soft_window(
        hard_events=hard_events,
        soft_state=soft_state,
        window_start=window_start,
        window_end=window_end,
    )
    created, updated = SoftEventService.apply_planner_actions(actions, planner_trace_id=trace_id)
    return {
        "actions": len(actions),
        "created": created,
        "updated": updated,
        "trace_id": trace_id,
    }
