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
