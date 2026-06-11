from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from orchestration.soft_scheduler import (
    collect_window_state,
    window_changed,
    default_window,
)
from orchestration.soft_planner import plan_soft_window
from orchestration.services import SoftEventService
from orchestration.models import OrchestrationSetting
from orchestration.objectives import ObjectiveService
from orchestration.tools.calendar import list_events

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Poll calendar + soft events for the next 2 weeks and detect changes (run every 5 minutes)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--window-days",
            type=int,
            default=14,
            help="Window length in days (default 14).",
        )

    def handle(self, *args, **options):
        window_days = options.get("window_days") or 14
        now = timezone.now()
        window_start = now
        window_end = now + timedelta(days=window_days)

        # Fetch hard events for the window.
        try:
            hard_resp = list_events(time_min=window_start.isoformat(), time_max=window_end.isoformat(), max_results=2500)
            hard_events = hard_resp.get("events", [])
        except Exception as exc:
            logger.exception("Failed to fetch calendar events for poll: %s", exc)
            return

        # Collect current soft state.
        soft_state = collect_window_state(window_start, window_end)
        soft_state["soft_events"] = [
            event
            for event in soft_state.get("soft_events", [])
            if str((event.get("metadata") or {}).get("source") or "") != ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE
        ]
        soft_state["objective_inputs"] = []

        # Hash and compare to last snapshot.
        prev_hash = OrchestrationSetting.objects.filter(key="soft_window_hash").first()
        prev_val = prev_hash.value if prev_hash else ""
        changed, new_hash = window_changed(prev_val, hard_events, soft_state)

        if not changed:
            logger.info("Soft planner window unchanged (hash=%s); skipping.", new_hash)
            return

        # Store new hash.
        OrchestrationSetting.objects.update_or_create(
            key="soft_window_hash", defaults={"value": new_hash}
        )

        actions, trace_id = plan_soft_window(
            hard_events=hard_events,
            soft_state=soft_state,
            window_start=window_start,
            window_end=window_end,
        )
        created, updated = SoftEventService.apply_planner_actions(actions, planner_trace_id=trace_id)
        logger.warning(
            "Soft planner applied: actions=%d created=%d updated=%d (hash=%s trace=%s)",
            len(actions),
            created,
            updated,
            new_hash,
            trace_id,
        )
