from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from orchestration.soft_scheduler import (
    collect_window_state,
    window_changed,
)
from orchestration.services import SoftEventService
from orchestration.models import Objective, OrchestrationSetting
from orchestration.objectives import ObjectiveService
from orchestration.tools.calendar import list_events
from orchestration.two_week_planner import TwoWeekPlannerService

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

        objectives = list(
            Objective.objects.all().select_related("parent", "chat").prefetch_related("tasks")
        )
        relevant = [
            objective
            for objective in objectives
            if ObjectiveService._should_schedule_objective(objective, window_start, window_end)
        ]
        objective_payloads, _urgent_task_ids = ObjectiveService._exact_schedule_payload(
            objectives=relevant,
            hard_events=hard_events,
            window_start=window_start,
            window_end=window_end,
        )
        objective_inputs = objective_payloads[0].get("objectives", []) if objective_payloads else []

        # Hash and compare to last snapshot.
        prev_hash = OrchestrationSetting.objects.filter(key="soft_window_hash").first()
        prev_val = prev_hash.value if prev_hash else ""
        # Exclude generated slots from the fingerprint: applying a plan must not
        # immediately trigger another plan. Input events and objective work do.
        changed, new_hash = window_changed(
            prev_val,
            hard_events,
            soft_state.get("soft_events", []),
            objective_inputs,
        )

        if not changed:
            logger.info("Soft planner window unchanged (hash=%s); skipping.", new_hash)
            return

        sessions, actions, trace_id, summary = TwoWeekPlannerService.plan(
            objectives=relevant,
            hard_events=hard_events,
            soft_state=soft_state,
            window_start=window_start,
            window_end=window_end,
        )
        with transaction.atomic():
            objective_sync = ObjectiveService._apply_objective_window_plan(
                objectives=objectives,
                relevant=relevant,
                session_plans=sessions,
                window_start=window_start,
                window_end=window_end,
            )
            created, updated = SoftEventService.apply_planner_actions(actions, planner_trace_id=trace_id)
            # A failed planner/apply pass must remain eligible for retry on the next poll.
            OrchestrationSetting.objects.update_or_create(
                key="soft_window_hash", defaults={"value": new_hash}
            )
        logger.warning(
            "Unified planner applied: actions=%d created=%d updated=%d objective_sessions=%d "
            "(hash=%s trace=%s summary=%s)",
            len(actions),
            created,
            updated,
            objective_sync.get("planned_slots", 0),
            new_hash,
            trace_id,
            summary,
        )
