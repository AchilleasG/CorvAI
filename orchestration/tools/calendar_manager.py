from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.utils import timezone

from orchestration.registry import register_function
from orchestration.tools import soft_events
from orchestration.tools import calendar as gcal
from orchestration.soft_scheduler import collect_window_state
from orchestration.soft_planner import plan_soft_window
from orchestration.services import SoftEventService

from orchestration.models import SoftEvent, SoftEventSlot, OrchestrationSetting

HABITS_KEY = "calendar_habits_text"


def _get_habits_value() -> str:
    setting = OrchestrationSetting.objects.filter(key=HABITS_KEY).first()
    return setting.value if setting else ""


def _set_habits_value(value: str) -> str:
    OrchestrationSetting.objects.update_or_create(
        key=HABITS_KEY,
        defaults={"value": value or ""},
    )
    return value or ""


def _get_soft_event(soft_event_id: str) -> Optional[SoftEvent]:
    try:
        return SoftEvent.objects.get(id=soft_event_id)
    except (SoftEvent.DoesNotExist, ValueError):
        return None

@register_function(
    manifest_id="calendar_manager.list_combined",
    module="calendar_manager",
    description="List hard (Google) and soft events together for a window.",
    params_schema={
        "type": "object",
        "properties": {
            "time_min": {"type": "string", "description": "ISO lower bound; defaults to now"},
            "time_max": {"type": "string", "description": "ISO upper bound; defaults to now+14d"},
            "max_results": {"type": "integer", "default": 250},
            "days": {"type": "integer", "default": 14, "description": "Used if time_max not provided"},
        },
    },
)
def list_combined(time_min: Optional[str] = None, time_max: Optional[str] = None, max_results: int = 250, days: int = 14):
    now = timezone.now()
    start = soft_events._parse_dt(time_min) or now
    end = soft_events._parse_dt(time_max) or (now + timedelta(days=days or 14))

    hard_resp = gcal.list_events(time_min=start.isoformat(), time_max=end.isoformat(), max_results=max_results)
    hard_events = hard_resp.get("events", [])

    soft_state = collect_window_state(start, end)
    mapped_hard = []
    for ev in hard_events:
        mapped_hard.append(
            {
                "id": ev.get("id"),
                "title": ev.get("summary") or "(no title)",
                "start": ev.get("start"),
                "end": ev.get("end"),
                "source": "hard",
            }
        )

    return {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "hard_events": mapped_hard,
        "soft_slots": [
            {
                "id": slot["id"],
                "soft_event_id": slot["soft_event_id"],
                "title": slot["title"],
                "start": slot["start_at"],
                "end": slot["end_at"],
                "status": slot["status"],
                "deferral_count": slot["deferral_count"],
                "rationale": slot["rationale"],
            }
            for slot in soft_state.get("slots", [])
        ],
        "soft_events_unscheduled": [
            {
                "id": se["id"],
                "title": se["title"],
                "notes": se.get("notes", ""),
                "priority": se["priority"],
                "soft_deadline": se["soft_deadline"],
                "hard_deadline": se["hard_deadline"],
            }
            for se in soft_state.get("soft_events", [])
            if se["status"] == "active"
        ],
    }


@register_function(
    manifest_id="calendar_manager.create_soft_event",
    module="calendar_manager",
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
            "deferral_limit": {"type": "integer", "default": 3},
            "priority": {"type": "integer", "default": 0, "description": "Higher = more urgent"},
            "chat_id": {"type": "string", "description": "Optional chat id for context/notifications"},
        },
        "required": ["title"],
    },
)
def create_soft_event(**kwargs):
    return soft_events.create_soft_event(**kwargs)


@register_function(
    manifest_id="calendar_manager.list_soft_events",
    module="calendar_manager",
    description="List soft events with optional event/slot status and time filters.",
    params_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by event status (active/paused/archived)"},
            "slot_status": {"type": "string", "description": "Optional slot status filter (planned, completed, etc.)"},
            "time_min": {"type": "string", "description": "ISO lower bound to filter slots"},
            "time_max": {"type": "string", "description": "ISO upper bound to filter slots"},
        },
    },
)
def list_soft_events(**kwargs):
    return soft_events.list_soft_events(**kwargs)


@register_function(
    manifest_id="calendar_manager.get_soft_event",
    module="calendar_manager",
    description="Get a soft event by id with its slots.",
    params_schema={
        "type": "object",
        "properties": {
            "soft_event_id": {"type": "string"},
            "slot_status": {"type": "string", "description": "Optional slot status filter (planned, completed, etc.)"},
            "time_min": {"type": "string", "description": "ISO lower bound to filter slots"},
            "time_max": {"type": "string", "description": "ISO upper bound to filter slots"},
        },
        "required": ["soft_event_id"],
    },
)
def get_soft_event(
    soft_event_id: str,
    slot_status: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
):
    se = _get_soft_event(soft_event_id)
    if not se:
        return {"found": False}

    slots_qs = SoftEventSlot.objects.filter(soft_event=se).order_by("start_at")
    if slot_status:
        slots_qs = slots_qs.filter(status=slot_status)
    if time_min:
        dt = soft_events._parse_dt(time_min)
        if dt:
            slots_qs = slots_qs.filter(start_at__gte=dt)
    if time_max:
        dt = soft_events._parse_dt(time_max)
        if dt:
            slots_qs = slots_qs.filter(end_at__lte=dt)

    slots = [
        {
            "id": str(sl.id),
            "start_at": sl.start_at.isoformat(),
            "end_at": sl.end_at.isoformat(),
            "notify_at": sl.notify_at.isoformat() if sl.notify_at else None,
            "status": sl.status,
            "deferral_count": sl.deferral_count,
            "rationale": sl.rationale,
        }
        for sl in slots_qs
    ]

    return {
        "found": True,
        "event": {
            "id": str(se.id),
            "title": se.title,
            "description": se.description,
            "notes": se.notes,
            "status": se.status,
            "priority": se.priority,
            "duration_minutes": se.duration_minutes,
            "soft_deadline": se.soft_deadline.isoformat() if se.soft_deadline else None,
            "hard_deadline": se.hard_deadline.isoformat() if se.hard_deadline else None,
        },
        "slots": slots,
    }


@register_function(
    manifest_id="calendar_manager.get_soft_event_notes",
    module="calendar_manager",
    description="Get notes for a soft event.",
    params_schema={
        "type": "object",
        "properties": {"soft_event_id": {"type": "string"}},
        "required": ["soft_event_id"],
    },
)
def get_soft_event_notes(soft_event_id: str):
    se = _get_soft_event(soft_event_id)
    if not se:
        return {"found": False}
    return {"found": True, "soft_event_id": str(se.id), "notes": se.notes}


@register_function(
    manifest_id="calendar_manager.set_soft_event_notes",
    module="calendar_manager",
    description="Overwrite notes for a soft event.",
    params_schema={
        "type": "object",
        "properties": {
            "soft_event_id": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["soft_event_id", "notes"],
    },
)
def set_soft_event_notes(soft_event_id: str, notes: str):
    se = _get_soft_event(soft_event_id)
    if not se:
        return {"updated": False}
    se.notes = notes or ""
    se.save(update_fields=["notes", "updated_at"])
    return {"updated": True, "soft_event_id": str(se.id), "notes": se.notes}


@register_function(
    manifest_id="calendar_manager.append_soft_event_notes",
    module="calendar_manager",
    description="Append notes for a soft event.",
    params_schema={
        "type": "object",
        "properties": {
            "soft_event_id": {"type": "string"},
            "notes": {"type": "string"},
            "separator": {"type": "string", "default": "\n"},
        },
        "required": ["soft_event_id", "notes"],
    },
)
def append_soft_event_notes(soft_event_id: str, notes: str, separator: str = "\n"):
    se = _get_soft_event(soft_event_id)
    if not se:
        return {"updated": False}
    base = se.notes or ""
    sep = separator if base and notes else ""
    se.notes = f"{base}{sep}{notes}".strip()
    se.save(update_fields=["notes", "updated_at"])
    return {"updated": True, "soft_event_id": str(se.id), "notes": se.notes}


@register_function(
    manifest_id="calendar_manager.clear_soft_event_notes",
    module="calendar_manager",
    description="Clear notes for a soft event.",
    params_schema={
        "type": "object",
        "properties": {"soft_event_id": {"type": "string"}},
        "required": ["soft_event_id"],
    },
)
def clear_soft_event_notes(soft_event_id: str):
    se = _get_soft_event(soft_event_id)
    if not se:
        return {"updated": False}
    se.notes = ""
    se.save(update_fields=["notes", "updated_at"])
    return {"updated": True, "soft_event_id": str(se.id)}


@register_function(
    manifest_id="calendar_manager.delete_soft_event_notes",
    module="calendar_manager",
    description="Delete notes for a soft event (alias of clear).",
    params_schema={
        "type": "object",
        "properties": {"soft_event_id": {"type": "string"}},
        "required": ["soft_event_id"],
    },
)
def delete_soft_event_notes(soft_event_id: str):
    return clear_soft_event_notes(soft_event_id)


@register_function(
    manifest_id="calendar_manager.promote_slot",
    module="calendar_manager",
    description="Promote a planned soft-event slot to a hard calendar event.",
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
def promote_slot(**kwargs):
    return soft_events.promote_slot(**kwargs)


@register_function(
    manifest_id="calendar_manager.replan_window",
    module="calendar_manager",
    description="Trigger a replan of the next N days with an optional note.",
    params_schema={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 14},
            "note": {"type": "string", "description": "Optional guidance for the planner (e.g., keep today free)."},
        },
    },
)
def replan_window(**kwargs):
    return soft_events.replan_window(**kwargs)


@register_function(
    manifest_id="calendar_manager.create_event",
    module="calendar_manager",
    description="Create a hard calendar event (Google Calendar).",
    params_schema={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Calendar id", "default": "primary"},
            "summary": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start datetime ISO 8601"},
            "end": {"type": "string", "description": "End datetime ISO 8601"},
            "timezone": {"type": "string", "description": "IANA timezone for start/end", "default": "UTC"},
            "description": {"type": "string", "description": "Event description"},
            "location": {"type": "string", "description": "Event location"},
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Email addresses to invite",
            },
        },
        "required": ["summary", "start", "end"],
    },
)
def create_event(**kwargs):
    return gcal.create_event(**kwargs)


@register_function(
    manifest_id="calendar_manager.update_event",
    module="calendar_manager",
    description="Update a hard calendar event (Google Calendar).",
    params_schema={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Calendar id", "default": "primary"},
            "event_id": {"type": "string", "description": "Event id to update"},
            "summary": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start datetime ISO 8601"},
            "end": {"type": "string", "description": "End datetime ISO 8601"},
            "timezone": {"type": "string", "description": "IANA timezone for start/end", "default": "UTC"},
            "description": {"type": "string", "description": "Event description"},
            "location": {"type": "string", "description": "Event location"},
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Email addresses to invite",
            },
        },
        "required": ["calendar_id", "event_id"],
    },
)
def update_event(**kwargs):
    return gcal.update_event(**kwargs)


@register_function(
    manifest_id="calendar_manager.delete_event",
    module="calendar_manager",
    description="Delete a hard calendar event (Google Calendar).",
    params_schema={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Calendar id", "default": "primary"},
            "event_id": {"type": "string", "description": "Event id to delete"},
        },
        "required": ["calendar_id", "event_id"],
    },
)
def delete_event(**kwargs):
    return gcal.delete_event(**kwargs)


@register_function(
    manifest_id="calendar_manager.delete_soft_event",
    module="calendar_manager",
    description="Delete (archive) a soft event and cancel its planned slots.",
    params_schema={
        "type": "object",
        "properties": {
            "soft_event_id": {"type": "string"},
        },
        "required": ["soft_event_id"],
    },
)
def delete_soft_event(soft_event_id: str):
    try:
        se = SoftEvent.objects.get(id=soft_event_id)
    except SoftEvent.DoesNotExist:
        return {"deleted": 0, "canceled_slots": 0}
    canceled = SoftEventSlot.objects.filter(soft_event=se).update(status=SoftEventSlot.STATUS_CANCELED)
    se.status = SoftEvent.STATUS_ARCHIVED
    se.save(update_fields=["status", "updated_at"])
    return {"deleted": 1, "canceled_slots": canceled}


@register_function(
    manifest_id="calendar_manager.get_habits",
    module="calendar_manager",
    description="Get scheduling habits and routine notes.",
    params_schema={"type": "object", "properties": {}},
)
def get_habits():
    return {"text": _get_habits_value()}


@register_function(
    manifest_id="calendar_manager.set_habits",
    module="calendar_manager",
    description="Overwrite scheduling habits and routine notes.",
    params_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Full habits text to store"},
        },
        "required": ["text"],
    },
)
def set_habits(text: str):
    return {"text": _set_habits_value(text)}


@register_function(
    manifest_id="calendar_manager.append_habits",
    module="calendar_manager",
    description="Append text to scheduling habits and routine notes.",
    params_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to append"},
            "separator": {"type": "string", "description": "Separator between entries", "default": "\n"},
        },
        "required": ["text"],
    },
)
def append_habits(text: str, separator: str = "\n"):
    base = _get_habits_value()
    sep = separator if base and text else ""
    return {"text": _set_habits_value(f"{base}{sep}{text}".strip())}


@register_function(
    manifest_id="calendar_manager.clear_habits",
    module="calendar_manager",
    description="Clear scheduling habits and routine notes.",
    params_schema={"type": "object", "properties": {}},
)
def clear_habits():
    _set_habits_value("")
    return {"cleared": True}


@register_function(
    manifest_id="calendar_manager.delete_habits",
    module="calendar_manager",
    description="Delete scheduling habits and routine notes (alias of clear).",
    params_schema={"type": "object", "properties": {}},
)
def delete_habits():
    _set_habits_value("")
    return {"deleted": True}


@register_function(
    manifest_id="calendar_manager.list_events",
    module="calendar_manager",
    description="List hard calendar events (Google Calendar).",
    params_schema={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Calendar id (default primary)", "default": "primary"},
            "time_min": {"type": "string", "description": "ISO datetime lower bound; defaults to now (UTC)"},
            "time_max": {"type": "string", "description": "ISO datetime upper bound"},
            "max_results": {"type": "integer", "description": "Max events to return (1-2500)", "default": 25},
            "query": {"type": "string", "description": "Free-text search filter"},
        },
    },
)
def list_events(**kwargs):
    return gcal.list_events(**kwargs)
