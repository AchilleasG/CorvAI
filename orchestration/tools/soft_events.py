from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta
import time as time_module
from typing import Any, Callable, Optional, List

from django.db import transaction
from django.utils import timezone

from orchestration.objectives import ObjectiveService
from orchestration.models import Chat, Job, JobEvent, Objective, SoftEvent, SoftEventSlot, ToolFunction
from orchestration.registry import register_function
from orchestration.services import JobService, SoftEventService
from orchestration.soft_scheduler import collect_window_state
from orchestration.tools.calendar import list_events
from orchestration.two_week_planner import TwoWeekPlannerService


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


class ReplanCanceled(Exception):
    pass


class SoftPlannerJobService:
    @staticmethod
    def _update_job(
        job: Job,
        *,
        progress: Optional[float] = None,
        summary: Optional[str] = None,
        message: str = "",
        payload: Optional[dict[str, Any]] = None,
        visibility: str = JobEvent.VISIBILITY_USER,
    ) -> None:
        update_fields: list[str] = []
        if progress is not None:
            job.progress = progress
            update_fields.append("progress")
        if summary is not None:
            job.user_visible_summary = summary
            update_fields.append("user_visible_summary")
        if update_fields:
            job.save(update_fields=update_fields + ["updated_at"])
        if message:
            JobService.append_event(
                job,
                role="soft_planner",
                event_type=JobEvent.EVENT_PROGRESS if progress is not None else JobEvent.EVENT_INFO,
                visibility=visibility,
                message=message,
                payload=payload or {},
            )

    @staticmethod
    def _cancel_check(job: Job) -> None:
        job.refresh_from_db(fields=["cancel_requested", "status"])
        if job.cancel_requested or job.status == Job.STATUS_CANCELED:
            raise ReplanCanceled("Calendar replan canceled")

    @staticmethod
    def _heartbeat(job: Job, progress: float, message: str, *, payload: Optional[dict[str, Any]] = None) -> None:
        JobService.heartbeat(job)
        SoftPlannerJobService._update_job(
            job,
            progress=progress,
            summary=message,
            message=message,
            payload=payload,
        )

    @staticmethod
    def _run_with_heartbeat(
        func: Callable[[], Any],
        *,
        job: Job,
        progress: float,
        heartbeat_message: str,
        heartbeat_seconds: float = 12.0,
    ) -> Any:
        start = time_module.monotonic()
        heartbeat_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func)
            while True:
                SoftPlannerJobService._cancel_check(job)
                try:
                    return future.result(timeout=heartbeat_seconds)
                except concurrent.futures.TimeoutError:
                    heartbeat_count += 1
                    elapsed = int(time_module.monotonic() - start)
                    SoftPlannerJobService._heartbeat(
                        job,
                        progress,
                        f"{heartbeat_message} ({elapsed}s elapsed, heartbeat {heartbeat_count})",
                        payload={"heartbeat_count": heartbeat_count, "elapsed_seconds": elapsed},
                    )

    @staticmethod
    def run_replan_job(job_id: str, *, days: int = 14, note: Optional[str] = None) -> dict[str, Any]:
        job = Job.objects.select_related("module", "active_function").get(id=job_id)
        replan_function = ToolFunction.objects.filter(manifest_id="soft_events.replan_window").first()
        job.status = Job.STATUS_RUNNING
        job.active_function = replan_function
        job.progress = 0.01
        job.user_visible_summary = "Starting calendar replan"
        job.save(update_fields=["status", "active_function", "progress", "user_visible_summary", "updated_at"])
        JobService.append_event(
            job,
            role="soft_planner",
            event_type=JobEvent.EVENT_STATE,
            visibility=JobEvent.VISIBILITY_USER,
            message="Started calendar replan",
            payload={"days": days, "note": note},
        )

        try:
            now = timezone.now()
            window_start = now
            window_end = now + timedelta(days=max(days or 1, 1))
            SoftPlannerJobService._update_job(
                job,
                progress=0.05,
                summary="Preparing objective replan",
                message="Preparing objective replan",
                payload={"window_start": window_start.isoformat(), "window_end": window_end.isoformat()},
            )

            SoftPlannerJobService._update_job(
                job,
                progress=0.08,
                summary="Collecting the complete two-week planning context",
                message="Collecting hard events, urgent objective tasks, and flexible events",
            )
            hard_resp = list_events(
                time_min=window_start.isoformat(),
                time_max=window_end.isoformat(),
                max_results=2500,
            )
            hard_events = hard_resp.get("events", [])
            objectives = list(
                Objective.objects.all().select_related("parent", "chat").prefetch_related("tasks")
            )
            relevant = [
                objective
                for objective in objectives
                if ObjectiveService._should_schedule_objective(objective, window_start, window_end)
            ]
            soft_state = collect_window_state(window_start, window_end)
            soft_state["soft_events"] = [
                event
                for event in soft_state.get("soft_events", [])
                if str((event.get("metadata") or {}).get("source") or "") != ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE
            ]
            soft_state["objective_inputs"] = []

            session_plans, actions, trace_id, planner_summary = SoftPlannerJobService._run_with_heartbeat(
                lambda: TwoWeekPlannerService.plan(
                    objectives=relevant,
                    hard_events=hard_events,
                    soft_state=soft_state,
                    window_start=window_start,
                    window_end=window_end,
                    planner_note=note,
                    progress_callback=lambda progress, message: SoftPlannerJobService._update_job(
                        job,
                        progress=progress,
                        summary=message,
                        message=message,
                    ),
                ),
                job=job,
                progress=0.4,
                heartbeat_message="Waiting for the unified two-week planner",
            )

            SoftPlannerJobService._update_job(
                job,
                progress=0.62,
                summary="Applying the validated two-week schedule",
                message="Replacing the previous plan only after local validation passed",
                payload={
                    "objective_session_count": len(session_plans),
                    "soft_slot_count": len(actions),
                    "trace_id": trace_id,
                },
            )
            SoftPlannerJobService._cancel_check(job)
            with transaction.atomic():
                objective_sync = ObjectiveService._apply_objective_window_plan(
                    objectives=objectives,
                    relevant=relevant,
                    session_plans=session_plans,
                    window_start=window_start,
                    window_end=window_end,
                )
                created, updated = SoftEventService.apply_planner_actions(actions, planner_trace_id=trace_id)

            SoftPlannerJobService._update_job(
                job,
                progress=0.96,
                summary="Computing urgent-task coverage",
                message="Computing urgent-task coverage",
            )
            coverage = ObjectiveService.coverage_snapshot(window_start, window_end)
            result = {
                "actions": len(actions),
                "created": created,
                "updated": updated,
                "trace_id": trace_id,
                "planner_summary": planner_summary,
                "model_calls": 1,
                "objective_sync": objective_sync,
                "coverage": coverage,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            }
            job.metadata = {**(job.metadata or {}), "result": result}
            job.save(update_fields=["metadata", "updated_at"])
            SoftPlannerJobService._update_job(
                job,
                progress=1.0,
                summary="Calendar replan completed",
                message="Calendar replan completed",
                payload=result,
            )
            JobService.mark_status(job, Job.STATUS_COMPLETED, progress=1.0)
            return result
        except ReplanCanceled as exc:
            SoftPlannerJobService._update_job(
                job,
                summary="Calendar replan canceled",
                message=str(exc),
            )
            JobService.mark_status(job, Job.STATUS_CANCELED, progress=job.progress)
            raise
        except Exception as exc:
            SoftPlannerJobService._update_job(
                job,
                summary="Calendar replan failed",
                message=str(exc),
                payload={"error": str(exc)},
            )
            JobService.mark_status(job, Job.STATUS_FAILED, error_summary=str(exc), progress=job.progress)
            raise


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
            "preferred_duration_minutes": {"type": "integer", "default": 60, "description": "Preferred duration in minutes"},
            "min_duration_minutes": {"type": "integer", "default": 30, "description": "Minimum acceptable duration"},
            "soft_deadline": {"type": "string", "description": "ISO datetime deadline (soft)"},
            "hard_deadline": {"type": "string", "description": "ISO datetime deadline (hard)"},
            "frequency": {"type": "string", "description": "Optional recurrence description (e.g., weekly)"},
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
    preferred_duration_minutes: int = 60,
    min_duration_minutes: int = 30,
    soft_deadline: Optional[str] = None,
    hard_deadline: Optional[str] = None,
    frequency: str = "",
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

    preferred = max(preferred_duration_minutes or 0, 1)
    minimum = max(min_duration_minutes or 0, 1)
    if minimum > preferred:
        minimum = preferred

    se = SoftEvent.objects.create(
        title=title,
        description=description or "",
        notes=notes or "",
        preferred_duration_minutes=preferred,
        min_duration_minutes=minimum,
        soft_deadline=_parse_dt(soft_deadline),
        hard_deadline=_parse_dt(hard_deadline),
        frequency=frequency or "",
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
                "preferred_duration_minutes": se.preferred_duration_minutes,
                "min_duration_minutes": se.min_duration_minutes,
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
    manifest_id="soft_events.mark_slot_outcome",
    module="soft_events",
    name="soft_events.mark_slot_outcome",
    description="Mark a planned soft-event session as completed or not performed and optionally log why.",
    params_schema={
        "type": "object",
        "properties": {
            "slot_id": {"type": "string"},
            "outcome": {"type": "string", "description": "completed or not_performed"},
            "reason": {"type": "string", "description": "Optional note about what happened or why it failed."},
            "minutes_spent": {"type": "integer", "description": "Optional number of minutes actually spent."},
            "completed_task_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional linked objective task ids to mark done when the session was completed.",
            },
        },
        "required": ["slot_id", "outcome"],
    },
)
def mark_slot_outcome(
    slot_id: str,
    outcome: str,
    reason: str = "",
    minutes_spent: Optional[int] = None,
    completed_task_ids: Optional[List[str]] = None,
):
    normalized = "not_performed" if outcome.strip().lower() in {"not_performed", "not_executed", "missed", "skipped"} else outcome
    return ObjectiveService.mark_slot_outcome(
        slot_id,
        outcome=normalized,
        reason=reason,
        minutes_spent=minutes_spent,
        completed_task_ids=completed_task_ids,
    )


@register_function(
    manifest_id="soft_events.replan_window",
    module="soft_events",
    name="soft_events.replan_window",
    description="Create one unified replacement schedule for the next N days from hard calendar events, deadline-bound objective tasks, and flexible events, with an optional user constraint.",
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
    objectives = list(
        Objective.objects.all().select_related("parent", "chat").prefetch_related("tasks")
    )
    relevant = [
        objective
        for objective in objectives
        if ObjectiveService._should_schedule_objective(objective, window_start, window_end)
    ]
    soft_state = collect_window_state(window_start, window_end)
    soft_state["soft_events"] = [
        event
        for event in soft_state.get("soft_events", [])
        if str((event.get("metadata") or {}).get("source") or "") != ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE
    ]
    soft_state["objective_inputs"] = []

    session_plans, actions, trace_id, planner_summary = TwoWeekPlannerService.plan(
        objectives=relevant,
        hard_events=hard_events,
        soft_state=soft_state,
        window_start=window_start,
        window_end=window_end,
        planner_note=note,
    )
    with transaction.atomic():
        objective_sync = ObjectiveService._apply_objective_window_plan(
            objectives=objectives,
            relevant=relevant,
            session_plans=session_plans,
            window_start=window_start,
            window_end=window_end,
        )
        created, updated = SoftEventService.apply_planner_actions(actions, planner_trace_id=trace_id)
    coverage = ObjectiveService.coverage_snapshot(window_start, window_end)
    return {
        "actions": len(actions),
        "created": created,
        "updated": updated,
        "trace_id": trace_id,
        "planner_summary": planner_summary,
        "model_calls": 1,
        "objective_sync": objective_sync,
        "coverage": coverage,
    }
