from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Optional, Sequence

from django.utils import timezone

from orchestration.model_providers import get_client, resolve_provider
from orchestration.models import Objective, OrchestrationSetting
from orchestration.objectives import MIN_SESSION_MINUTES, ObjectiveService, SessionPlan
from orchestration.services import ModelConfigService, UsageService, UserInfoService


class TwoWeekPlannerService:
    """Create one complete rolling-window schedule with one model request."""

    @staticmethod
    def _compact_hard_events(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": event.get("id"),
                "title": event.get("title") or event.get("summary"),
                "description": event.get("description"),
                "location": event.get("location"),
                "start": event.get("start"),
                "end": event.get("end"),
                "all_day": bool(event.get("all_day")),
            }
            for event in events
            if isinstance(event, dict)
        ]

    @staticmethod
    def _compact_soft_events(soft_state: dict[str, Any]) -> list[dict[str, Any]]:
        compact: list[dict[str, Any]] = []
        for event in soft_state.get("soft_events", []):
            if not isinstance(event, dict):
                continue
            compact.append(
                {
                    "id": event.get("id"),
                    "title": event.get("title"),
                    "description": event.get("description"),
                    "notes": event.get("notes"),
                    "preferred_duration_minutes": event.get("preferred_duration_minutes"),
                    "min_duration_minutes": event.get("min_duration_minutes"),
                    "soft_deadline": event.get("soft_deadline"),
                    "hard_deadline": event.get("hard_deadline"),
                    "frequency": event.get("frequency"),
                    "priority": event.get("priority"),
                    "deferral_limit": event.get("deferral_limit"),
                }
            )
        return compact

    @staticmethod
    def _prompt(planner_note: Optional[str]) -> str:
        note = f"\nUser planning instruction (hard constraint): {planner_note}\n" if planner_note else ""
        habits = ObjectiveService._clean_text(
            OrchestrationSetting.objects.filter(key="calendar_habits_text")
            .values_list("value", flat=True)
            .first()
        )
        profile = UserInfoService.format_core_profile_block()
        profile_block = f"\nUser profile:\n{profile}" if profile else ""
        habits_block = f"\nScheduling habits:\n{habits}" if habits else ""
        return (
            "Create one coherent schedule for the supplied rolling planning window. This is the only planning pass.\n"
            "The input contains fixed hard calendar events, deadline-relevant objective tasks, and independent flexible events.\n"
            "Return JSON only with keys objective_sessions, soft_event_slots, and summary.\n"
            "objective_sessions entries require objective_id, task_ids, title, description, notes, priority, start_at, end_at, notify_at, rationale.\n"
            "soft_event_slots entries require soft_event_id, start_at, end_at, notify_at, rationale.\n"
            "The output is a complete replacement plan, so return only the new sessions and slots that should exist.\n"
            "Rules:\n"
            "- Timed hard events are absolute, immovable blocks. Never overlap them.\n"
            "- All-day items are context unless their description explicitly represents occupied time. Reminder-style events are non-blocking.\n"
            "- Never overlap two items in your own output.\n"
            "- Every supplied objective task must be covered before its task or objective deadline. A task may appear in multiple sessions when its effort needs that.\n"
            "- Choose both the number and duration of sessions from remaining effort, difficulty, deadlines, and actual free time.\n"
            "- A session may combine related tasks from the same objective.\n"
            "- Flexible-event durations must stay between their minimum and preferred durations. Respect deadlines, frequency, priority, and deferral limits.\n"
            "- Prefer sustainable daytime/evening hours, sensible transition buffers, and spreading demanding work across days. Use late nights only under genuine deadline pressure.\n"
            "- Use concise rationales and do not repeat the input in the output.\n"
            f"{note}"
            f"{profile_block}"
            f"{habits_block}"
        )

    @staticmethod
    def _request(
        payload: dict[str, Any],
        *,
        planner_note: Optional[str],
        model: Optional[str],
    ) -> tuple[dict[str, Any], str]:
        model_name = model or ModelConfigService.get_soft_planner_model()
        provider = resolve_provider(model_name)
        prompt = TwoWeekPlannerService._prompt(planner_note)
        payload_json = json.dumps(payload, default=str, separators=(",", ":"))
        if provider == "openai":
            response = get_client("openai").responses.create(
                model=model_name,
                input=[
                    {"role": "developer", "content": [{"type": "input_text", "text": prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": payload_json}]},
                ],
                text={"format": {"type": "json_object"}, "verbosity": "low"},
                reasoning={"effort": "medium"},
                store=False,
                timeout=150,
            )
            usage = getattr(response, "usage", None)
            if usage:
                UsageService.log_usage(
                    source="calendar_two_week_plan",
                    model=model_name,
                    cache_mode=ModelConfigService.get_cache_mode(),
                    usage=usage,
                    job=None,
                )
            raw = getattr(response, "output_text", "") or "{}"
        else:
            response = get_client("xai").chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": payload_json},
                ],
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content if getattr(response, "choices", None) else "{}"
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            raise ValueError("The two-week planner returned an invalid response")
        return data, model_name

    @staticmethod
    def _task_deadline(objective: Objective, task_ids: Sequence[str], window_end: datetime) -> datetime:
        deadlines = [
            task.due_at
            for task in ObjectiveService._select_actionable_tasks(objective)
            if str(task.id) in task_ids and task.due_at
        ]
        if objective.deadline_at:
            deadlines.append(objective.deadline_at)
        return min(deadlines) if deadlines else window_end

    @staticmethod
    def _parse_objective_sessions(
        items: Any,
        *,
        objectives: Sequence[Objective],
        window_end: datetime,
    ) -> list[SessionPlan]:
        objective_map = {str(objective.id): objective for objective in objectives}
        plans: list[SessionPlan] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            objective = objective_map.get(str(item.get("objective_id") or ""))
            if objective is None:
                continue
            valid_task_ids = {str(task.id) for task in ObjectiveService._select_actionable_tasks(objective)}
            task_ids = [
                str(task_id)
                for task_id in (item.get("task_ids") or [])
                if str(task_id) in valid_task_ids
            ]
            if not task_ids:
                continue
            start_at = ObjectiveService._parse_iso_datetime(item.get("start_at"))
            end_at = ObjectiveService._parse_iso_datetime(item.get("end_at"))
            if not start_at or not end_at or end_at <= start_at:
                continue
            duration = max(int((end_at - start_at).total_seconds() // 60), MIN_SESSION_MINUTES)
            deadline = TwoWeekPlannerService._task_deadline(objective, task_ids, window_end)
            plans.append(
                SessionPlan(
                    title=ObjectiveService._first_nonempty(item.get("title"), objective.title)[:255],
                    description=ObjectiveService._first_nonempty(item.get("description"), objective.description, f"Work on {objective.title}"),
                    notes=ObjectiveService._session_notes_for_objective(
                        objective,
                        task_ids,
                        extra_notes=str(item.get("notes") or ""),
                    ),
                    preferred_minutes=duration,
                    min_minutes=duration,
                    soft_deadline=deadline,
                    hard_deadline=deadline,
                    priority=max(int(item.get("priority") or objective.priority or 0), 0),
                    task_ids=list(dict.fromkeys(task_ids)),
                    metadata={
                        "source": ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
                        "objective_id": str(objective.id),
                        "objective_source": ObjectiveService._objective_source(objective),
                        "task_ids": list(dict.fromkeys(task_ids)),
                        "planner_mode": "unified_two_week",
                    },
                    start_at=start_at,
                    end_at=end_at,
                    notify_at=ObjectiveService._parse_iso_datetime(item.get("notify_at")),
                    rationale=str(item.get("rationale") or "").strip(),
                )
            )
        return plans

    @staticmethod
    def _parse_soft_slots(
        items: Any,
        *,
        soft_state: dict[str, Any],
        hard_events: Sequence[dict[str, Any]],
        objective_sessions: Sequence[SessionPlan],
        window_start: datetime,
        window_end: datetime,
    ) -> list[dict[str, Any]]:
        event_map = {
            str(item.get("id")): item
            for item in soft_state.get("soft_events", [])
            if isinstance(item, dict) and item.get("id")
        }
        blocked = ObjectiveService._blocked_intervals_from_hard_events(hard_events)
        occupied = [
            (plan.start_at, plan.end_at)
            for plan in objective_sessions
            if plan.start_at and plan.end_at
        ]
        actions: list[dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("soft_event_id") or "")
            event = event_map.get(event_id)
            start_at = ObjectiveService._parse_iso_datetime(item.get("start_at"))
            end_at = ObjectiveService._parse_iso_datetime(item.get("end_at"))
            if event is None or not start_at or not end_at or end_at <= start_at:
                continue
            if start_at < window_start or end_at > window_end:
                continue
            duration = int((end_at - start_at).total_seconds() // 60)
            minimum = max(int(event.get("min_duration_minutes") or 1), 1)
            preferred = max(int(event.get("preferred_duration_minutes") or minimum), minimum)
            if duration < minimum or duration > preferred:
                continue
            deadline = ObjectiveService._parse_iso_datetime(event.get("hard_deadline") or event.get("soft_deadline"))
            if deadline and end_at > deadline:
                continue
            if any(ObjectiveService._intervals_overlap(start_at, end_at, a, b) for a, b in [*blocked, *occupied]):
                continue
            occupied.append((start_at, end_at))
            notify_at = ObjectiveService._parse_iso_datetime(item.get("notify_at"))
            actions.append(
                {
                    "type": "create_slot",
                    "soft_event_id": event_id,
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "notify_at": notify_at.isoformat() if notify_at else None,
                    "rationale": str(item.get("rationale") or "").strip(),
                    "metadata": {"planner_mode": "unified_two_week"},
                }
            )
        return actions

    @staticmethod
    def plan(
        *,
        objectives: Sequence[Objective],
        hard_events: Sequence[dict[str, Any]],
        soft_state: dict[str, Any],
        window_start: datetime,
        window_end: datetime,
        planner_note: Optional[str] = None,
        model: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> tuple[list[SessionPlan], list[dict[str, Any]], str, str]:
        objective_payloads, urgent_task_ids = ObjectiveService._exact_schedule_payload(
            objectives=objectives,
            hard_events=hard_events,
            window_start=window_start,
            window_end=window_end,
        )
        payload = {
            "window": {"start": window_start.isoformat(), "end": window_end.isoformat(), "now": timezone.now().isoformat()},
            "hard_events": TwoWeekPlannerService._compact_hard_events(hard_events),
            "objectives": objective_payloads[0].get("objectives", []) if objective_payloads else [],
            "soft_events": TwoWeekPlannerService._compact_soft_events(soft_state),
        }
        if progress_callback:
            progress_callback(
                0.28,
                f"Sending one unified planning request with {len(payload['hard_events'])} hard events, "
                f"{len(payload['objectives'])} objectives, {len(urgent_task_ids)} urgent tasks, and "
                f"{len(payload['soft_events'])} flexible events",
            )
        started = time.monotonic()
        data, _model_name = TwoWeekPlannerService._request(payload, planner_note=planner_note, model=model)
        if progress_callback:
            progress_callback(0.48, f"Unified planning request returned after {int(time.monotonic() - started)}s; validating locally")
        sessions = TwoWeekPlannerService._parse_objective_sessions(
            data.get("objective_sessions"), objectives=objectives, window_end=window_end
        )
        valid_sessions, issues, covered = ObjectiveService._validate_exact_session_plans(
            sessions,
            objectives=objectives,
            hard_events=hard_events,
            window_start=window_start,
            window_end=window_end,
        )
        missing = sorted(urgent_task_ids - covered)
        required_minutes: dict[str, int] = {}
        for objective in objectives:
            for task in ObjectiveService._select_actionable_tasks(objective):
                task_id = str(task.id)
                if task_id in urgent_task_ids:
                    required_minutes[task_id] = max(
                        int(task.remaining_effort_minutes or task.estimated_effort_minutes or 0),
                        0,
                    )
        scheduled_minutes = {task_id: 0 for task_id in urgent_task_ids}
        for session in valid_sessions:
            if not session.start_at or not session.end_at:
                continue
            duration = max(int((session.end_at - session.start_at).total_seconds() // 60), 0)
            for task_id in session.task_ids:
                if task_id in scheduled_minutes:
                    scheduled_minutes[task_id] += duration
        partial = sorted(
            task_id
            for task_id, required in required_minutes.items()
            if required > 0 and scheduled_minutes.get(task_id, 0) < required
        )
        if issues or missing or partial:
            details = [
                *issues[:10],
                *(f"Uncovered urgent task: {task_id}" for task_id in missing[:20]),
                *(
                    f"Insufficient scheduled effort for task {task_id}: "
                    f"{scheduled_minutes.get(task_id, 0)}/{required_minutes[task_id]} minutes"
                    for task_id in partial[:20]
                ),
            ]
            raise ValueError("Unified two-week plan failed validation: " + "; ".join(details))
        soft_actions = TwoWeekPlannerService._parse_soft_slots(
            data.get("soft_event_slots"),
            soft_state=soft_state,
            hard_events=hard_events,
            objective_sessions=valid_sessions,
            window_start=window_start,
            window_end=window_end,
        )
        urgent_soft_ids = {
            str(event.get("id"))
            for event in soft_state.get("soft_events", [])
            if isinstance(event, dict)
            and event.get("id")
            and (
                (deadline := ObjectiveService._parse_iso_datetime(event.get("hard_deadline") or event.get("soft_deadline")))
                is not None
                and deadline <= window_end
            )
        }
        scheduled_soft_ids = {str(action.get("soft_event_id")) for action in soft_actions}
        missing_soft = sorted(urgent_soft_ids - scheduled_soft_ids)
        if missing_soft:
            raise ValueError(
                "Unified two-week plan failed validation: unscheduled deadline-bound flexible events: "
                + ", ".join(missing_soft[:20])
            )
        return valid_sessions, soft_actions, str(uuid.uuid4()), str(data.get("summary") or "").strip()


__all__ = ["TwoWeekPlannerService"]
