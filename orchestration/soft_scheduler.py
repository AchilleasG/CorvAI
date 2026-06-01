from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Iterable, Dict, Any, Tuple, List

from django.utils import timezone

from orchestration.services import SoftEventService

OBJECTIVE_SOFT_EVENT_SOURCE = "objective_scheduler"


def stable_hash(payload: Any) -> str:
    """
    Generate a stable hash for change detection in the 2-week window.
    """
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def window_changed(
    prev_hash: str,
    hard_events: Iterable[dict],
    soft_events: Iterable[dict],
    objective_inputs: Iterable[dict] | None = None,
) -> Tuple[bool, str]:
    """
    Compare current 2-week window state to a previous hash.
    hard_events should already be normalized dicts (id, start, end, summary, updated_at).
    soft_events likewise (id, title, planned slots, deadlines).
    """
    current_hash = stable_hash(
        {
            "hard": list(hard_events),
            "soft": list(soft_events),
            "objectives": list(objective_inputs or []),
        }
    )
    return current_hash != prev_hash, current_hash


def collect_window_state(
    window_start: datetime,
    window_end: datetime,
    *,
    include_objective_derived: bool = True,
) -> Dict[str, Any]:
    """
    Snapshot soft events and slots for a window to pass into the planner.
    """
    soft_events = SoftEventService.list_soft_events_for_window(window_start, window_end)
    slots = SoftEventService.list_slots_for_window(window_start, window_end)
    if not include_objective_derived:
        objective_soft_ids = {
            str(se.id)
            for se in soft_events
            if isinstance(getattr(se, "metadata", None), dict)
            and se.metadata.get("source") == OBJECTIVE_SOFT_EVENT_SOURCE
        }
        if objective_soft_ids:
            soft_events = [se for se in soft_events if str(se.id) not in objective_soft_ids]
            slots = [slot for slot in slots if str(slot.soft_event_id) not in objective_soft_ids]
    return {
        "soft_events": [
            {
                "id": str(se.id),
                "title": se.title,
                "preferred_duration_minutes": se.preferred_duration_minutes,
                "min_duration_minutes": se.min_duration_minutes,
                "soft_deadline": se.soft_deadline.isoformat() if se.soft_deadline else None,
                "hard_deadline": se.hard_deadline.isoformat() if se.hard_deadline else None,
                "description": se.description,
                "notes": se.notes,
                "priority": se.priority,
                "deferral_limit": se.deferral_limit,
                "frequency": se.frequency,
                "status": se.status,
            }
            for se in soft_events
        ],
        "slots": [
            {
                "id": str(slot.id),
                "soft_event_id": str(slot.soft_event_id),
                "start_at": slot.start_at.isoformat(),
                "end_at": slot.end_at.isoformat(),
                "status": slot.status,
                "deferral_count": slot.deferral_count,
                "notify_at": slot.notify_at.isoformat() if slot.notify_at else None,
            }
            for slot in slots
        ],
    }


def default_window(now: datetime | None = None) -> Tuple[datetime, datetime]:
    now = now or timezone.now()
    end = now + timedelta(days=14)
    return now, end
