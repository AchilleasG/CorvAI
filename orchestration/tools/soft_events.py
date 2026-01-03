from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from django.utils import timezone

from orchestration.models import SoftEvent, Chat
from orchestration.registry import register_function


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
