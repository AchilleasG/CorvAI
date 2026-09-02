from __future__ import annotations

import concurrent.futures
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
import time as time_module
from typing import Any, Callable, Iterable, Optional, Sequence

from django.db import transaction, models
from django.utils import timezone

from orchestration.model_providers import get_client, resolve_provider
from orchestration.models import (
    HardEventTaskLink,
    Objective,
    OrchestrationSetting,
    ObjectiveLog,
    ObjectiveTask,
    SoftEvent,
    SoftEventObjective,
    SoftEventSlot,
    SoftEventTask,
)
from orchestration.services import ModelConfigService, SoftEventService, UsageService, UserInfoService
from orchestration.soft_planner import plan_soft_window
from orchestration.soft_scheduler import collect_window_state
from orchestration.tools.calendar import list_events


DEFAULT_ASSIGNMENT_SESSION_MINUTES = 120
DEFAULT_TOPIC_SESSION_MINUTES = 90
DEFAULT_GENERIC_SESSION_MINUTES = 60
MIN_SESSION_MINUTES = 30


@dataclass
class SessionPlan:
    title: str
    description: str
    notes: str
    preferred_minutes: int
    min_minutes: int
    soft_deadline: Optional[datetime]
    hard_deadline: Optional[datetime]
    priority: int
    task_ids: list[str]
    metadata: dict
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    notify_at: Optional[datetime] = None
    rationale: str = ""


class ObjectiveService:
    OBJECTIVE_SOFT_EVENT_SOURCE = "objective_scheduler"
    SLOT_UNASSIGN_STATUSES = [
        SoftEventSlot.STATUS_PLANNED,
        SoftEventSlot.STATUS_DEFERRED,
        SoftEventSlot.STATUS_PROMOTED,
    ]

    @staticmethod
    def _clean_text(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _emit_scheduler_progress(
        progress_callback: Optional[Callable[[float, str], None]],
        progress: float,
        message: str,
    ) -> None:
        if progress_callback:
            progress_callback(progress, message)

    @staticmethod
    def _ensure_not_canceled(cancel_check: Optional[Callable[[], None]]) -> None:
        if cancel_check:
            cancel_check()

    @staticmethod
    def _call_with_heartbeat(
        func: Callable[[], Any],
        *,
        heartbeat_message: str,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
        progress: float = 0.0,
        heartbeat_seconds: float = 12.0,
    ) -> Any:
        start = time_module.monotonic()
        heartbeat_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func)
            while True:
                ObjectiveService._ensure_not_canceled(cancel_check)
                try:
                    return future.result(timeout=heartbeat_seconds)
                except concurrent.futures.TimeoutError:
                    heartbeat_count += 1
                    elapsed = int(time_module.monotonic() - start)
                    ObjectiveService._emit_scheduler_progress(
                        progress_callback,
                        progress,
                        f"{heartbeat_message} ({elapsed}s elapsed, heartbeat {heartbeat_count})",
                    )

    @staticmethod
    def _objective_source(objective: Objective) -> str:
        metadata = objective.metadata if isinstance(objective.metadata, dict) else {}
        return str(metadata.get("source") or "").strip()

    @staticmethod
    def _first_nonempty(*values: object) -> str:
        for value in values:
            text = ObjectiveService._clean_text(value)
            if text:
                return text
        return ""

    @staticmethod
    def _nearest_course_deadline(course) -> Optional[datetime]:
        exam_dt = (
            course.exams.exclude(scheduled_at__isnull=True)
            .order_by("scheduled_at")
            .values_list("scheduled_at", flat=True)
            .first()
        )
        if exam_dt:
            return exam_dt
        if course.term_end_date:
            term_end = datetime.combine(course.term_end_date, datetime.min.time()).replace(hour=23, minute=59)
            if timezone.is_naive(term_end):
                return timezone.make_aware(term_end)
            return term_end
        return None

    @staticmethod
    def _nearest_course_deadline(course) -> Optional[datetime]:
        # Use the next upcoming exam so objectives stay relevant after past exams.
        now = timezone.now()
        exam_dt = (
            course.exams.exclude(scheduled_at__isnull=True)
            .filter(scheduled_at__gte=now)
            .order_by("scheduled_at")
            .values_list("scheduled_at", flat=True)
            .first()
        )
        if exam_dt:
            return exam_dt
        # All exams have passed — fall back to the most recent one.
        exam_dt = (
            course.exams.exclude(scheduled_at__isnull=True)
            .order_by("-scheduled_at")
            .values_list("scheduled_at", flat=True)
            .first()
        )
        if exam_dt:
            return exam_dt
        if course.term_end_date:
            term_end = datetime.combine(course.term_end_date, datetime.min.time()).replace(hour=23, minute=59)
            if timezone.is_naive(term_end):
                return timezone.make_aware(term_end)
            return term_end
        return None

    @staticmethod
    def _upcoming_exams_for_objective(objective: Objective) -> list[dict[str, Any]]:
        from study.models import StudyExam
        study_course_id = (objective.metadata or {}).get("study_course_id")
        if not study_course_id:
            return []
        now = timezone.now()
        exams = (
            StudyExam.objects
            .filter(course_id=study_course_id, scheduled_at__isnull=False, scheduled_at__gte=now)
            .order_by("scheduled_at")
        )
        return [
            {
                "title": exam.title,
                "kind": exam.kind,
                "scheduled_at": exam.scheduled_at.isoformat(),
            }
            for exam in exams
        ]

    @staticmethod
    def create_course_objective(*, title: str, description: str = "", chat=None) -> Objective:
        return Objective.objects.create(
            title=title[:255],
            description=description or "",
            notes=f"Study course objective for {title}".strip(),
            chat=chat,
            metadata={"source": "study_course"},
        )

    @staticmethod
    def create_child_objective(
        *,
        parent: Objective,
        title: str,
        description: str = "",
        deadline_at: Optional[datetime] = None,
        estimated_effort_minutes: Optional[int] = None,
        remaining_effort_minutes: Optional[int] = None,
        priority: int = 0,
        metadata: Optional[dict] = None,
        chat=None,
    ) -> Objective:
        return Objective.objects.create(
            parent=parent,
            title=title[:255],
            description=description or "",
            deadline_at=deadline_at,
            estimated_effort_minutes=estimated_effort_minutes,
            remaining_effort_minutes=remaining_effort_minutes,
            priority=priority,
            chat=chat or parent.chat,
            metadata=metadata or {},
        )

    @staticmethod
    def _sum_child_remaining(objective: Objective) -> Optional[int]:
        child_values = [
            value
            for value in objective.children.values_list("remaining_effort_minutes", flat=True)
            if isinstance(value, int)
        ]
        task_values = [
            task.remaining_effort_minutes
            if isinstance(task.remaining_effort_minutes, int)
            else task.estimated_effort_minutes
            for task in objective.tasks.exclude(status__in=[ObjectiveTask.STATUS_DONE, ObjectiveTask.STATUS_CANCELED])
        ]
        combined = [int(value) for value in [*child_values, *task_values] if isinstance(value, int)]
        if combined:
            return sum(combined)
        return None

    @staticmethod
    def _upsert_task(
        *,
        objective: Objective,
        external_key: str,
        title: str,
        description: str = "",
        sort_order: int = 0,
        due_at: Optional[datetime] = None,
        estimated_effort_minutes: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> ObjectiveTask:
        task, _created = ObjectiveTask.objects.get_or_create(
            objective=objective,
            metadata__external_key=external_key,
            defaults={
                "title": title[:255],
                "description": description,
                "sort_order": max(int(sort_order or 0), 0),
                "due_at": due_at,
                "estimated_effort_minutes": estimated_effort_minutes,
                "remaining_effort_minutes": estimated_effort_minutes,
                "metadata": {"external_key": external_key, **(metadata or {})},
            },
        )
        updates: list[str] = []
        merged_metadata = {"external_key": external_key, **(task.metadata or {}), **(metadata or {})}
        if task.title != title[:255]:
            task.title = title[:255]
            updates.append("title")
        if task.description != description:
            task.description = description
            updates.append("description")
        normalized_sort = max(int(sort_order or 0), 0)
        if task.sort_order != normalized_sort:
            task.sort_order = normalized_sort
            updates.append("sort_order")
        if task.due_at != due_at:
            task.due_at = due_at
            updates.append("due_at")
        if task.estimated_effort_minutes != estimated_effort_minutes:
            task.estimated_effort_minutes = estimated_effort_minutes
            updates.append("estimated_effort_minutes")
        if task.remaining_effort_minutes is None and estimated_effort_minutes is not None:
            task.remaining_effort_minutes = estimated_effort_minutes
            updates.append("remaining_effort_minutes")
        if task.metadata != merged_metadata:
            task.metadata = merged_metadata
            updates.append("metadata")
        if updates:
            task.save(update_fields=updates + ["updated_at"])
        return task

    @staticmethod
    @transaction.atomic
    def ensure_course_objective(course) -> Objective:
        objective = course.objective
        deadline = ObjectiveService._nearest_course_deadline(course)
        remaining = ObjectiveService._sum_child_remaining(objective)
        title = ObjectiveService._first_nonempty(course.code, course.title) or course.title
        description = course.description or ""
        notes = f"Study course objective for {course.title}".strip()
        metadata = {
            **(objective.metadata or {}),
            "source": "study_course",
            "study_course_id": str(course.id),
        }
        updates: list[str] = []
        if objective.title != title:
            objective.title = title
            updates.append("title")
        if objective.description != description:
            objective.description = description
            updates.append("description")
        desired_status = Objective.STATUS_ACTIVE
        if course.status == "completed":
            desired_status = Objective.STATUS_COMPLETED
        elif course.status == "archived":
            desired_status = Objective.STATUS_PAUSED
        if objective.status != desired_status:
            objective.status = desired_status
            updates.append("status")
        if objective.deadline_at != deadline:
            objective.deadline_at = deadline
            updates.append("deadline_at")
        if objective.notes != notes:
            objective.notes = notes
            updates.append("notes")
        if objective.chat_id != course.chat_id:
            objective.chat = course.chat
            updates.append("chat")
        if objective.remaining_effort_minutes != remaining:
            objective.remaining_effort_minutes = remaining
            updates.append("remaining_effort_minutes")
        if objective.metadata != metadata:
            objective.metadata = metadata
            updates.append("metadata")
        if updates:
            objective.save(update_fields=updates + ["updated_at"])
        return objective

    @staticmethod
    @transaction.atomic
    def ensure_topic_objective(topic) -> Objective:
        objective = topic.objective
        parent = topic.course.objective
        title = f"Study {topic.name}"
        description = ObjectiveService._first_nonempty(topic.summary, topic.description)
        remaining = ObjectiveService._sum_child_remaining(objective) or max(int(topic.estimated_effort_minutes or 60), 1)
        metadata = {
            **(objective.metadata or {}),
            "source": "study_topic",
            "study_course_id": str(topic.course_id),
            "study_topic_id": str(topic.id),
            "topic_status": topic.status,
        }
        updates: list[str] = []
        if objective.parent_id != parent.id:
            objective.parent = parent
            updates.append("parent")
        desired_status = Objective.STATUS_COMPLETED if topic.passed or topic.status == "mastered" else Objective.STATUS_ACTIVE
        if objective.status != desired_status:
            objective.status = desired_status
            updates.append("status")
        if objective.title != title:
            objective.title = title
            updates.append("title")
        if objective.description != description:
            objective.description = description
            updates.append("description")
        if objective.deadline_at != parent.deadline_at:
            objective.deadline_at = parent.deadline_at
            updates.append("deadline_at")
        if objective.estimated_effort_minutes != max(int(topic.estimated_effort_minutes or 60), 1):
            objective.estimated_effort_minutes = max(int(topic.estimated_effort_minutes or 60), 1)
            updates.append("estimated_effort_minutes")
        if objective.remaining_effort_minutes != remaining:
            objective.remaining_effort_minutes = remaining
            updates.append("remaining_effort_minutes")
        priority = int(round(float(topic.weight or 1.0) * 10))
        if objective.priority != priority:
            objective.priority = priority
            updates.append("priority")
        if objective.chat_id != topic.course.chat_id:
            objective.chat = topic.course.chat
            updates.append("chat")
        if objective.metadata != metadata:
            objective.metadata = metadata
            updates.append("metadata")
        if updates:
            objective.save(update_fields=updates + ["updated_at"])
        ObjectiveService.sync_topic_tasks(topic)
        return objective

    @staticmethod
    @transaction.atomic
    def ensure_assignment_objective(assignment) -> Objective:
        objective = getattr(assignment, "objective", None)
        parent = assignment.course.objective
        if objective is None:
            objective = ObjectiveService.create_child_objective(
                parent=parent,
                title=f"Complete {assignment.title}",
                description=ObjectiveService._first_nonempty(assignment.plan, assignment.description),
                deadline_at=assignment.due_at,
                estimated_effort_minutes=max(
                    int(assignment.session_count or 1) * DEFAULT_ASSIGNMENT_SESSION_MINUTES,
                    MIN_SESSION_MINUTES,
                ),
                remaining_effort_minutes=max(
                    int(assignment.session_count or 1) * DEFAULT_ASSIGNMENT_SESSION_MINUTES,
                    MIN_SESSION_MINUTES,
                ),
                priority=8,
                metadata={
                    "source": "study_assignment",
                    "study_course_id": str(assignment.course_id),
                    "study_assignment_id": str(assignment.id),
                    "assignment_status": assignment.status,
                },
                chat=assignment.course.chat,
            )
            assignment.objective = objective
            assignment.save(update_fields=["objective", "updated_at"])
        title = f"Complete {assignment.title}"
        description = ObjectiveService._first_nonempty(assignment.plan, assignment.description)
        estimated = max(int(assignment.session_count or 1) * DEFAULT_ASSIGNMENT_SESSION_MINUTES, MIN_SESSION_MINUTES)
        remaining = ObjectiveService._sum_child_remaining(objective) or estimated
        metadata = {
            **(objective.metadata or {}),
            "source": "study_assignment",
            "study_course_id": str(assignment.course_id),
            "study_assignment_id": str(assignment.id),
            "assignment_status": assignment.status,
        }
        updates: list[str] = []
        if objective.parent_id != parent.id:
            objective.parent = parent
            updates.append("parent")
        desired_status = Objective.STATUS_COMPLETED if assignment.status in {"submitted", "graded"} else Objective.STATUS_ACTIVE
        if objective.status != desired_status:
            objective.status = desired_status
            updates.append("status")
        if objective.title != title:
            objective.title = title
            updates.append("title")
        if objective.description != description:
            objective.description = description
            updates.append("description")
        if objective.deadline_at != assignment.due_at:
            objective.deadline_at = assignment.due_at
            updates.append("deadline_at")
        if objective.estimated_effort_minutes != estimated:
            objective.estimated_effort_minutes = estimated
            updates.append("estimated_effort_minutes")
        if objective.remaining_effort_minutes != remaining:
            objective.remaining_effort_minutes = remaining
            updates.append("remaining_effort_minutes")
        if objective.priority != 8:
            objective.priority = 8
            updates.append("priority")
        if objective.chat_id != assignment.course.chat_id:
            objective.chat = assignment.course.chat
            updates.append("chat")
        if objective.metadata != metadata:
            objective.metadata = metadata
            updates.append("metadata")
        if updates:
            objective.save(update_fields=updates + ["updated_at"])
        ObjectiveService.sync_assignment_tasks(assignment)
        return objective

    @staticmethod
    @transaction.atomic
    def sync_topic_tasks(topic) -> list[ObjectiveTask]:
        objective = topic.objective
        seen_keys: set[str] = set()
        tasks: list[ObjectiveTask] = []
        homework_items = topic.homework if isinstance(topic.homework, list) else []
        deadline = topic.course.objective.deadline_at
        for idx, item in enumerate(homework_items, start=1):
            if not isinstance(item, dict):
                continue
            title = ObjectiveService._clean_text(item.get("source_exercise_label")) or f"Homework item {idx}"
            text = ObjectiveService._clean_text(item.get("text"))
            if not text:
                continue
            assignment_id = ObjectiveService._clean_text(item.get("assignment_id")) or f"topic-homework-{idx}"
            external_key = f"topic-homework:{assignment_id}"
            seen_keys.add(external_key)
            task = ObjectiveService._upsert_task(
                objective=objective,
                external_key=external_key,
                title=title,
                description=text,
                sort_order=idx,
                due_at=deadline,
                estimated_effort_minutes=None,
                metadata={
                    "source": "study_topic_homework",
                    "assignment_id": assignment_id,
                    "source_material_id": item.get("source_material_id"),
                    "source_material_title": item.get("source_material_title"),
                    "question_index": item.get("question_index"),
                },
            )
            desired_status = ObjectiveTask.STATUS_DONE if bool(item.get("done")) else ObjectiveTask.STATUS_TODO
            if task.status != desired_status:
                task.status = desired_status
                task.completed_at = timezone.now() if desired_status == ObjectiveTask.STATUS_DONE else None
                task.save(update_fields=["status", "completed_at", "updated_at"])
            tasks.append(task)
        stale_qs = objective.tasks.filter(metadata__source="study_topic_homework").exclude(
            metadata__external_key__in=list(seen_keys) or [""]
        )
        stale_qs.update(status=ObjectiveTask.STATUS_CANCELED, updated_at=timezone.now())
        objective.remaining_effort_minutes = ObjectiveService._sum_child_remaining(objective) or max(
            int(topic.estimated_effort_minutes or 60), 1
        )
        objective.save(update_fields=["remaining_effort_minutes", "updated_at"])
        return tasks

    @staticmethod
    @transaction.atomic
    def sync_assignment_tasks(assignment) -> list[ObjectiveTask]:
        objective = assignment.objective
        if objective is None:
            return []
        checklist = assignment.checklist if isinstance(assignment.checklist, list) else []
        seen_keys: set[str] = set()
        tasks: list[ObjectiveTask] = []
        estimated_each = None
        if checklist:
            estimated_each = max(
                int((objective.estimated_effort_minutes or DEFAULT_ASSIGNMENT_SESSION_MINUTES) / max(len(checklist), 1)),
                MIN_SESSION_MINUTES,
            )
        for idx, item in enumerate(checklist, start=1):
            if not isinstance(item, dict):
                continue
            title = ObjectiveService._clean_text(item.get("title")) or f"Assignment step {idx}"
            description = ObjectiveService._clean_text(item.get("description"))
            external_key = f"assignment-checklist:{idx}"
            seen_keys.add(external_key)
            task = ObjectiveService._upsert_task(
                objective=objective,
                external_key=external_key,
                title=title,
                description=description,
                sort_order=int(item.get("step_number") or idx),
                due_at=assignment.due_at,
                estimated_effort_minutes=estimated_each,
                metadata={
                    "source": "study_assignment_checklist",
                    "step_number": int(item.get("step_number") or idx),
                },
            )
            tasks.append(task)
        stale_qs = objective.tasks.filter(metadata__source="study_assignment_checklist").exclude(
            metadata__external_key__in=list(seen_keys) or [""]
        )
        stale_qs.update(status=ObjectiveTask.STATUS_CANCELED, updated_at=timezone.now())
        objective.remaining_effort_minutes = ObjectiveService._sum_child_remaining(objective) or max(
            int(assignment.session_count or 1) * DEFAULT_ASSIGNMENT_SESSION_MINUTES,
            MIN_SESSION_MINUTES,
        )
        objective.save(update_fields=["remaining_effort_minutes", "updated_at"])
        return tasks

    @staticmethod
    def _select_actionable_tasks(objective: Objective) -> list[ObjectiveTask]:
        tasks = list(
            objective.tasks.exclude(status__in=[ObjectiveTask.STATUS_DONE, ObjectiveTask.STATUS_CANCELED])
            .order_by("sort_order", "created_at")
        )
        return tasks

    @staticmethod
    def _relevant_tasks_for_window(
        objective: Objective,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ObjectiveTask]:
        tasks = ObjectiveService._select_actionable_tasks(objective)
        if objective.deadline_at and objective.deadline_at <= window_end:
            return tasks
        return [task for task in tasks if task.due_at and task.due_at <= window_end]

    @staticmethod
    def _preferred_minutes_for_objective(objective: Objective) -> int:
        source = ObjectiveService._objective_source(objective)
        if source == "study_assignment":
            return DEFAULT_ASSIGNMENT_SESSION_MINUTES
        if source == "study_topic":
            return DEFAULT_TOPIC_SESSION_MINUTES
        return DEFAULT_GENERIC_SESSION_MINUTES

    @staticmethod
    def _slot_history_for_objective(objective: Objective, *, limit: int = 12) -> list[dict[str, Any]]:
        slots = list(
            SoftEventSlot.objects.filter(soft_event__objective_links__objective=objective)
            .select_related("soft_event")
            .order_by("-start_at", "-created_at")[:limit]
        )
        history: list[dict[str, Any]] = []
        for slot in slots:
            slot_metadata = slot.metadata if isinstance(slot.metadata, dict) else {}
            history.append(
                {
                    "slot_id": str(slot.id),
                    "soft_event_id": str(slot.soft_event_id),
                    "soft_event_title": slot.soft_event.title,
                    "status": slot.status,
                    "start_at": slot.start_at.isoformat(),
                    "end_at": slot.end_at.isoformat(),
                    "duration_minutes": max(int((slot.end_at - slot.start_at).total_seconds() // 60), 0),
                    "rationale": slot.rationale,
                    "minutes_spent": slot_metadata.get("minutes_spent"),
                    "outcome_reason": slot_metadata.get("outcome_reason") or slot_metadata.get("execution_note"),
                    "completed_task_ids": slot_metadata.get("completed_task_ids") or [],
                }
            )
        return history

    @staticmethod
    def _recent_logs_for_objective(objective: Objective, *, limit: int = 12) -> list[dict[str, Any]]:
        logs = list(objective.logs.select_related("task").order_by("-logged_at", "-created_at")[:limit])
        return [
            {
                "log_id": str(log.id),
                "task_id": str(log.task_id) if log.task_id else None,
                "task_title": log.task.title if log.task_id else None,
                "kind": log.kind,
                "text": log.text,
                "minutes_spent": log.minutes_spent,
                "logged_at": log.logged_at.isoformat() if log.logged_at else None,
                "metadata": log.metadata or {},
            }
            for log in logs
        ]

    @staticmethod
    def _should_schedule_objective(objective: Objective, window_start: datetime, window_end: datetime) -> bool:
        if objective.status != Objective.STATUS_ACTIVE:
            return False
        source = ObjectiveService._objective_source(objective)
        tasks = ObjectiveService._relevant_tasks_for_window(objective, window_start, window_end)
        has_direct_work = bool(tasks) or bool(objective.remaining_effort_minutes or objective.estimated_effort_minutes)
        if source == "study_course" and not tasks:
            return False
        if not has_direct_work:
            return False
        if objective.deadline_at and objective.deadline_at <= window_end:
            return True
        for task in tasks:
            if task.due_at and task.due_at <= window_end:
                return True
        has_existing = SoftEvent.objects.filter(
            objective_links__objective=objective,
            metadata__source=ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
            status=SoftEvent.STATUS_ACTIVE,
        ).exists()
        return has_existing

    @staticmethod
    def _build_sessions_for_objective(objective: Objective) -> list[SessionPlan]:
        tasks = ObjectiveService._select_actionable_tasks(objective)
        preferred = max(ObjectiveService._preferred_minutes_for_objective(objective), MIN_SESSION_MINUTES)
        minimum = max(min(preferred, max(preferred // 2, MIN_SESSION_MINUTES)), MIN_SESSION_MINUTES)
        remaining = objective.remaining_effort_minutes or objective.estimated_effort_minutes
        if remaining is None:
            task_minutes = [
                int(task.remaining_effort_minutes or task.estimated_effort_minutes or 0)
                for task in tasks
                if int(task.remaining_effort_minutes or task.estimated_effort_minutes or 0) > 0
            ]
            remaining = sum(task_minutes) if task_minutes else preferred
        remaining = max(int(remaining), MIN_SESSION_MINUTES)
        session_count = max(int(ceil(remaining / preferred)), 1)
        task_groups: list[list[ObjectiveTask]] = [[] for _ in range(session_count)]
        if tasks:
            for idx, task in enumerate(tasks):
                task_groups[idx % session_count].append(task)

        sessions: list[SessionPlan] = []
        for index in range(session_count):
            group = task_groups[index]
            task_lines = [f"- {task.title}: {task.description}".strip(": ") for task in group]
            notes = [f"Objective: {objective.title}"]
            if task_lines:
                notes.append("Tasks:\n" + "\n".join(task_lines))
            source = ObjectiveService._objective_source(objective)
            if source:
                notes.append(f"Objective source: {source}")
            session_title = objective.title if session_count == 1 else f"{objective.title} — Session {index + 1}"
            sessions.append(
                SessionPlan(
                    title=session_title[:255],
                    description=objective.description or f"Work on {objective.title}",
                    notes="\n\n".join(bit for bit in notes if bit).strip(),
                    preferred_minutes=preferred,
                    min_minutes=minimum,
                    soft_deadline=objective.deadline_at,
                    hard_deadline=objective.deadline_at,
                    priority=max(int(objective.priority or 0), 0),
                    task_ids=[str(task.id) for task in group],
                    metadata={
                        "source": ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
                        "objective_id": str(objective.id),
                        "objective_source": source,
                        "session_number": index + 1,
                        "session_count": session_count,
                    },
                )
            )
        return sessions

    @staticmethod
    def _normalize_session_task_ids(
        objective: Objective,
        session_task_ids: Sequence[str],
        valid_task_ids: set[str],
    ) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for task_id in session_task_ids:
            text = str(task_id or "").strip()
            if text and text in valid_task_ids and text not in seen:
                seen.add(text)
                normalized.append(text)
        if normalized:
            return normalized
        fallback_tasks = ObjectiveService._select_actionable_tasks(objective)
        return [str(task.id) for task in fallback_tasks[:1]]

    @staticmethod
    def _session_notes_for_objective(
        objective: Objective,
        task_ids: Sequence[str],
        *,
        extra_notes: str = "",
    ) -> str:
        task_map = {
            str(task.id): task
            for task in ObjectiveService._select_actionable_tasks(objective)
        }
        notes = [f"Objective: {objective.title}"]
        task_lines: list[str] = []
        for task_id in task_ids:
            task = task_map.get(str(task_id))
            if not task:
                continue
            due_text = task.due_at.isoformat() if task.due_at else (
                objective.deadline_at.isoformat() if objective.deadline_at else "No explicit deadline"
            )
            task_lines.append(f"- {task.title} (due: {due_text})")
        if task_lines:
            notes.append("Tasks:\n" + "\n".join(task_lines))
        source = ObjectiveService._objective_source(objective)
        if source:
            notes.append(f"Objective source: {source}")
        if extra_notes.strip():
            notes.append(extra_notes.strip())
        return "\n\n".join(bit for bit in notes if bit).strip()

    @staticmethod
    def _parse_iso_datetime(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
            except Exception:
                return None
        else:
            return None
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone=timezone.get_current_timezone())
        return dt

    @staticmethod
    def _hard_event_match_key(event_id: Any, start_raw: Any, end_raw: Any) -> tuple[str, str, str]:
        return (
            str(event_id or "").strip(),
            str(start_raw or "").strip(),
            str(end_raw or "").strip(),
        )

    @staticmethod
    def _matched_hard_event_links(
        window_start: datetime,
        window_end: datetime,
        *,
        hard_events: Optional[Sequence[dict[str, Any]]] = None,
    ) -> tuple[dict[tuple[str, str, str], list[HardEventTaskLink]], dict[str, list[dict[str, Any]]]]:
        if hard_events is None:
            hard_events = list_events(
                time_min=window_start.isoformat(),
                time_max=window_end.isoformat(),
                max_results=2500,
            ).get("events", [])
        event_index: dict[tuple[str, str, str], dict[str, Any]] = {}
        for event in hard_events:
            if not isinstance(event, dict):
                continue
            key = ObjectiveService._hard_event_match_key(event.get("id"), event.get("start"), event.get("end"))
            if not key[0]:
                continue
            event_index[key] = event
        matched_by_event: dict[tuple[str, str, str], list[HardEventTaskLink]] = {}
        matched_by_task: dict[str, list[dict[str, Any]]] = {}
        link_qs = (
            HardEventTaskLink.objects.select_related("task__objective")
            .filter(event_start_at__lt=window_end, event_end_at__gt=window_start)
            .exclude(task__status__in=[ObjectiveTask.STATUS_DONE, ObjectiveTask.STATUS_CANCELED, ObjectiveTask.STATUS_BLOCKED])
        )
        for link in link_qs:
            key = ObjectiveService._hard_event_match_key(link.event_id, link.event_start_raw, link.event_end_raw)
            event = event_index.get(key)
            if not event:
                continue
            matched_by_event.setdefault(key, []).append(link)
            matched_by_task.setdefault(str(link.task_id), []).append(event)
        return matched_by_event, matched_by_task

    @staticmethod
    def _task_ids_covered_by_hard_events(
        tasks: Sequence[ObjectiveTask],
        *,
        window_start: datetime,
        window_end: datetime,
        hard_events: Optional[Sequence[dict[str, Any]]] = None,
        matched_by_task: Optional[dict[str, list[dict[str, Any]]]] = None,
    ) -> set[str]:
        if matched_by_task is None:
            _, matched_by_task = ObjectiveService._matched_hard_event_links(
                window_start,
                window_end,
                hard_events=hard_events,
            )
        covered: set[str] = set()
        for task in tasks:
            deadline = task.due_at or window_end
            for event in matched_by_task.get(str(task.id), []):
                start, _end = ObjectiveService._event_bounds(event)
                if start and start <= deadline:
                    covered.add(str(task.id))
                    break
        return covered

    @staticmethod
    def _event_bounds(event: dict[str, Any]) -> tuple[Optional[datetime], Optional[datetime]]:
        start = ObjectiveService._parse_iso_datetime(event.get("start"))
        end = ObjectiveService._parse_iso_datetime(event.get("end"))
        return start, end

    @staticmethod
    def _intervals_overlap(
        a_start: datetime,
        a_end: datetime,
        b_start: datetime,
        b_end: datetime,
    ) -> bool:
        return a_start < b_end and a_end > b_start

    @staticmethod
    def _is_nonblocking_reminder(event: dict[str, Any]) -> bool:
        description = str(event.get("description") or "")
        return "reminder" in description.lower()

    @staticmethod
    def _blocked_intervals_from_hard_events(hard_events: Sequence[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
        blocked: list[tuple[datetime, datetime]] = []
        for event in hard_events:
            if not isinstance(event, dict):
                continue
            if event.get("all_day"):
                continue
            if ObjectiveService._is_nonblocking_reminder(event):
                continue
            start, end = ObjectiveService._event_bounds(event)
            if start and end and end > start:
                blocked.append((start, end))
        blocked.sort(key=lambda item: item[0])
        return blocked

    @staticmethod
    def _task_deadline(task: ObjectiveTask, objective: Objective, window_end: datetime) -> datetime:
        if task.due_at:
            return task.due_at
        if objective.deadline_at:
            return objective.deadline_at
        return window_end

    @staticmethod
    def _validate_exact_session_plans(
        plans: Sequence[SessionPlan],
        *,
        objectives: Sequence[Objective],
        hard_events: Sequence[dict[str, Any]],
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[list[SessionPlan], list[str], set[str]]:
        objective_map = {str(objective.id): objective for objective in objectives}
        blocked = ObjectiveService._blocked_intervals_from_hard_events(hard_events)
        valid: list[SessionPlan] = []
        issues: list[str] = []
        covered_task_ids: set[str] = set()
        occupied: list[tuple[datetime, datetime, str]] = []

        for index, plan in enumerate(plans, start=1):
            metadata = plan.metadata or {}
            objective_id = str(metadata.get("objective_id") or "").strip()
            objective = objective_map.get(objective_id)
            if objective is None:
                issues.append(f"Session {index} references unknown objective {objective_id}.")
                continue
            if not plan.start_at or not plan.end_at or plan.end_at <= plan.start_at:
                issues.append(f"Session {index} for {objective.title} has invalid timing.")
                continue
            if plan.start_at < window_start or plan.end_at > window_end:
                issues.append(f"Session {index} for {objective.title} falls outside the planning window.")
                continue
            if any(
                ObjectiveService._intervals_overlap(plan.start_at, plan.end_at, busy_start, busy_end)
                for busy_start, busy_end in blocked
            ):
                issues.append(f"Session {index} for {objective.title} overlaps a hard event.")
                continue
            if any(
                ObjectiveService._intervals_overlap(plan.start_at, plan.end_at, busy_start, busy_end)
                for busy_start, busy_end, _title in occupied
            ):
                issues.append(f"Session {index} for {objective.title} overlaps another planned session.")
                continue

            duration_minutes = max(int((plan.end_at - plan.start_at).total_seconds() // 60), 0)
            if duration_minutes <= 0:
                issues.append(f"Session {index} for {objective.title} has non-positive duration.")
                continue
            plan.preferred_minutes = max(int(plan.preferred_minutes or duration_minutes), duration_minutes)
            plan.min_minutes = max(min(int(plan.min_minutes or duration_minutes), plan.preferred_minutes), 1)
            if duration_minutes < plan.min_minutes or duration_minutes > plan.preferred_minutes:
                plan.preferred_minutes = duration_minutes
                plan.min_minutes = duration_minutes

            task_map = {
                str(task.id): task
                for task in ObjectiveService._select_actionable_tasks(objective)
            }
            valid_task_ids = [task_id for task_id in plan.task_ids if task_id in task_map]
            if not valid_task_ids:
                issues.append(f"Session {index} for {objective.title} does not cover any valid task.")
                continue
            deadline_missed = False
            for task_id in valid_task_ids:
                task = task_map[task_id]
                deadline = ObjectiveService._task_deadline(task, objective, window_end)
                if plan.end_at > deadline:
                    issues.append(f"Session {index} for {objective.title} ends after task deadline for {task.title}.")
                    deadline_missed = True
                    break
            if deadline_missed:
                continue

            plan.task_ids = valid_task_ids
            valid.append(plan)
            occupied.append((plan.start_at, plan.end_at, plan.title))
            covered_task_ids.update(valid_task_ids)

        return valid, issues, covered_task_ids

    @staticmethod
    def _exact_schedule_prompt(
        *,
        planner_note: Optional[str] = None,
    ) -> str:
        planner_note_block = f"Planner note (hard constraint): {planner_note}\n" if planner_note else ""
        habits = (
            OrchestrationSetting.objects.filter(key="calendar_habits_text")
            .values_list("value", flat=True)
            .first()
            or ""
        )
        habits_block = f"\nScheduling habits:\n{habits}" if habits else ""
        core_profile_block = UserInfoService.format_core_profile_block()
        core_notes = f"\nCore user context:\n{core_profile_block}" if core_profile_block else ""
        return (
            "You are planning urgent objective sessions for the next 14 days.\n"
            "You must decide BOTH how many sessions are needed AND the exact time each session will happen.\n"
            "Do not first invent sessions abstractly and leave timing for later. Timing and session-count are one joint decision.\n"
            "Only include objectives or tasks whose deadline falls within the planning window. Skip everything else.\n"
            "Return JSON only with keys: sessions, summary.\n"
            "Each session must include: objective_id, title, description, notes, priority, task_ids, start_at, end_at, notify_at, rationale.\n"
            "Rules:\n"
            "- Every urgent task in the window MUST appear in at least one session before its deadline.\n"
            "- A session may cover multiple tasks.\n"
            "- A difficult task may appear in multiple sessions.\n"
            "- You must choose the number of sessions based on the actual free time available in the calendar.\n"
            "- If time is tight, compress work into fewer or shorter sessions rather than leaving tasks unscheduled.\n"
            "- If the situation is genuinely dire, late-night work is allowed, but use it sparingly and place it on the least harmful day.\n"
            "- Use hard-event titles, descriptions, locations, and exact timed blocks as authoritative context.\n"
            "- Timed hard events are immovable. All-day events are context only, not blocked time. Reminder-style events are non-blocking.\n"
            "- Do not overlap hard events.\n"
            "- Do not overlap other planned sessions in your own output.\n"
            "- Prefer realistic buffers when the schedule allows, but urgent coverage takes precedence.\n"
            "- Do not leave urgent work unscheduled merely because the placement is imperfect.\n"
            f"{planner_note_block}"
            f"{core_notes}"
            f"{habits_block}"
        )

    @staticmethod
    def _exact_schedule_payload(
        *,
        objectives: Sequence[Objective],
        hard_events: Sequence[dict[str, Any]],
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        objective_payload: list[dict[str, Any]] = []
        urgent_task_ids: set[str] = set()
        _matched_by_event, matched_by_task = ObjectiveService._matched_hard_event_links(
            window_start,
            window_end,
            hard_events=hard_events,
        )
        for objective in objectives:
            relevant_tasks = ObjectiveService._relevant_tasks_for_window(objective, window_start, window_end)
            hard_covered_task_ids = ObjectiveService._task_ids_covered_by_hard_events(
                relevant_tasks,
                window_start=window_start,
                window_end=window_end,
                hard_events=hard_events,
                matched_by_task=matched_by_task,
            )
            uncovered_relevant_tasks = [task for task in relevant_tasks if str(task.id) not in hard_covered_task_ids]
            include_deadline_only_objective = (
                objective.deadline_at
                and objective.deadline_at <= window_end
                and not relevant_tasks
            )
            if not uncovered_relevant_tasks and not include_deadline_only_objective:
                continue
            for task in uncovered_relevant_tasks:
                urgent_task_ids.add(str(task.id))
            objective_payload.append(
                {
                    "id": str(objective.id),
                    "title": objective.title,
                    "description": objective.description,
                    "deadline_at": objective.deadline_at.isoformat() if objective.deadline_at else None,
                    "priority": objective.priority,
                    "remaining_effort_minutes": objective.remaining_effort_minutes,
                    "estimated_effort_minutes": objective.estimated_effort_minutes,
                    "source": ObjectiveService._objective_source(objective),
                    "notes": objective.notes,
                    "tasks": [
                        {
                            "id": str(task.id),
                            "title": task.title,
                            "description": task.description,
                            "status": task.status,
                            "due_at": task.due_at.isoformat() if task.due_at else None,
                            "estimated_effort_minutes": task.estimated_effort_minutes,
                            "remaining_effort_minutes": task.remaining_effort_minutes,
                        }
                        for task in uncovered_relevant_tasks
                    ],
                    "hard_scheduled_task_ids": sorted(hard_covered_task_ids),
                    "recent_logs": ObjectiveService._recent_logs_for_objective(objective),
                }
            )
        payload = {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "hard_events": list(hard_events),
            "objectives": objective_payload,
        }
        return [payload], urgent_task_ids

    @staticmethod
    def _request_exact_schedule_sessions(
        *,
        objectives: Sequence[Objective],
        hard_events: Sequence[dict[str, Any]],
        window_start: datetime,
        window_end: datetime,
        planner_note: Optional[str] = None,
        model: str | None = None,
        retry_feedback: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
        progress: float = 0.0,
        attempt_label: str = "attempt 1",
    ) -> list[SessionPlan]:
        payloads, urgent_task_ids = ObjectiveService._exact_schedule_payload(
            objectives=objectives,
            hard_events=hard_events,
            window_start=window_start,
            window_end=window_end,
        )
        if not payloads or not payloads[0]["objectives"]:
            ObjectiveService._emit_scheduler_progress(
                progress_callback,
                progress,
                f"Skipping exact objective scheduling {attempt_label}: no urgent objectives in window",
            )
            return []
        payload = payloads[0]
        payload_json = json.dumps(payload, default=str)
        model_name = model or ModelConfigService.get_soft_planner_model()
        provider = resolve_provider(model_name)
        prompt = ObjectiveService._exact_schedule_prompt(planner_note=planner_note)
        if retry_feedback:
            prompt += f"\nPrevious attempt failed validation:\n{retry_feedback}\nFix those issues completely.\n"
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            progress,
            (
                f"Sending exact objective scheduling request {attempt_label} "
                f"({len(payload['objectives'])} objectives, {len(urgent_task_ids)} urgent tasks, "
                f"{len(hard_events)} hard events, {len(payload_json)} payload chars, model {model_name})"
            ),
        )

        def _make_request() -> list[dict[str, Any]]:
            if provider == "openai":
                resp = get_client("openai").responses.create(
                    model=model_name,
                    input=[
                        {"role": "developer", "content": [{"type": "input_text", "text": prompt}]},
                        {"role": "user", "content": [{"type": "input_text", "text": payload_json}]},
                    ],
                    text={"format": {"type": "json_object"}, "verbosity": "low"},
                    reasoning={"effort": "medium"},
                    store=False,
                    timeout=120,
                )
                usage_obj = getattr(resp, "usage", None)
                if usage_obj:
                    UsageService.log_usage(
                        source="objective_exact_schedule",
                        model=model_name,
                        cache_mode=ModelConfigService.get_cache_mode(),
                        usage=usage_obj,
                        job=None,
                    )
                raw = getattr(resp, "output_text", "") or "{}"
                data = json.loads(raw)
            else:
                resp = get_client("xai").chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": payload_json},
                    ],
                    response_format={"type": "json_object"},
                )
                raw = "{}"
                if getattr(resp, "choices", None):
                    raw = resp.choices[0].message.content or "{}"  # type: ignore[assignment]
                data = json.loads(raw)
            return data.get("sessions") if isinstance(data.get("sessions"), list) else []

        request_started = time_module.monotonic()
        try:
            sessions_raw = ObjectiveService._call_with_heartbeat(
                _make_request,
                heartbeat_message="Waiting for exact objective scheduling model",
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                progress=progress,
            )
            elapsed = int(time_module.monotonic() - request_started)
            ObjectiveService._emit_scheduler_progress(
                progress_callback,
                progress,
                f"Exact objective scheduling request {attempt_label} returned {len(sessions_raw)} raw sessions after {elapsed}s",
            )
        except Exception as exc:
            sessions_raw = []
            elapsed = int(time_module.monotonic() - request_started)
            ObjectiveService._emit_scheduler_progress(
                progress_callback,
                progress,
                f"Exact objective scheduling request {attempt_label} failed after {elapsed}s: {type(exc).__name__}: {exc}",
            )

        objective_map = {str(objective.id): objective for objective in objectives}
        plans: list[SessionPlan] = []
        for item in sessions_raw:
            if not isinstance(item, dict):
                continue
            objective_id = str(item.get("objective_id") or "").strip()
            objective = objective_map.get(objective_id)
            if objective is None:
                continue
            valid_task_ids = {str(task.id) for task in ObjectiveService._select_actionable_tasks(objective)}
            task_ids = ObjectiveService._normalize_session_task_ids(
                objective,
                item.get("task_ids") if isinstance(item.get("task_ids"), list) else [],
                valid_task_ids,
            )
            start_at = ObjectiveService._parse_iso_datetime(item.get("start_at"))
            end_at = ObjectiveService._parse_iso_datetime(item.get("end_at"))
            notify_at = ObjectiveService._parse_iso_datetime(item.get("notify_at"))
            duration_minutes = max(int(((end_at - start_at).total_seconds() // 60) if start_at and end_at else 0), 0)
            preferred_minutes = duration_minutes or ObjectiveService._preferred_minutes_for_objective(objective)
            notes = ObjectiveService._session_notes_for_objective(
                objective,
                task_ids,
                extra_notes=str(item.get("notes") or ""),
            )
            plans.append(
                SessionPlan(
                    title=ObjectiveService._first_nonempty(item.get("title"), objective.title)[:255],
                    description=ObjectiveService._first_nonempty(item.get("description"), objective.description, f"Work on {objective.title}"),
                    notes=notes,
                    preferred_minutes=max(preferred_minutes, MIN_SESSION_MINUTES),
                    min_minutes=max(min(duration_minutes or MIN_SESSION_MINUTES, max((duration_minutes or MIN_SESSION_MINUTES) // 2, MIN_SESSION_MINUTES)), 1),
                    soft_deadline=objective.deadline_at,
                    hard_deadline=objective.deadline_at,
                    priority=max(int(item.get("priority") or objective.priority or 0), 0),
                    task_ids=task_ids,
                    metadata={
                        "source": ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
                        "objective_id": str(objective.id),
                        "objective_source": ObjectiveService._objective_source(objective),
                        "task_ids": task_ids,
                        "planner_mode": "single_pass_exact",
                    },
                    start_at=start_at,
                    end_at=end_at,
                    notify_at=notify_at,
                    rationale=str(item.get("rationale") or "").strip(),
                )
            )
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            progress,
            f"Parsed exact objective scheduling request {attempt_label} into {len(plans)} session plans",
        )
        return plans

    @staticmethod
    def _scheduled_session_plans_for_window(
        objectives: Sequence[Objective],
        *,
        hard_events: Sequence[dict[str, Any]],
        window_start: datetime,
        window_end: datetime,
        planner_note: Optional[str] = None,
        model: str | None = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> list[SessionPlan]:
        payloads, urgent_task_ids = ObjectiveService._exact_schedule_payload(
            objectives=objectives,
            hard_events=hard_events,
            window_start=window_start,
            window_end=window_end,
        )
        if not payloads or not payloads[0]["objectives"]:
            return []

        first_pass = ObjectiveService._request_exact_schedule_sessions(
            objectives=objectives,
            hard_events=hard_events,
            window_start=window_start,
            window_end=window_end,
            planner_note=planner_note,
            model=model,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            progress=0.22,
            attempt_label="attempt 1",
        )
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            0.26,
            f"Validating exact objective scheduling attempt 1 ({len(first_pass)} planned sessions)",
        )
        valid, issues, covered = ObjectiveService._validate_exact_session_plans(
            first_pass,
            objectives=objectives,
            hard_events=hard_events,
            window_start=window_start,
            window_end=window_end,
        )
        missing = sorted(urgent_task_ids - covered)
        if not issues and not missing:
            ObjectiveService._emit_scheduler_progress(
                progress_callback,
                0.28,
                f"Exact objective scheduling attempt 1 passed validation with {len(valid)} sessions covering all {len(covered)} urgent tasks",
            )
            return valid

        retry_feedback = "\n".join(
            [*issues[:20], *(f"Urgent task not covered: {task_id}" for task_id in missing[:20])]
        )
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            0.3,
            (
                "Retrying exact objective scheduling after validation found problems: "
                f"{len(issues)} invalid-session issues, {len(missing)} uncovered urgent tasks"
            ),
        )
        second_pass = ObjectiveService._request_exact_schedule_sessions(
            objectives=objectives,
            hard_events=hard_events,
            window_start=window_start,
            window_end=window_end,
            planner_note=planner_note,
            model=model,
            retry_feedback=retry_feedback,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            progress=0.32,
            attempt_label="attempt 2",
        )
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            0.36,
            f"Validating exact objective scheduling attempt 2 ({len(second_pass)} planned sessions)",
        )
        valid_retry, issues_retry, covered_retry = ObjectiveService._validate_exact_session_plans(
            second_pass,
            objectives=objectives,
            hard_events=hard_events,
            window_start=window_start,
            window_end=window_end,
        )
        missing_retry = sorted(urgent_task_ids - covered_retry)
        if issues_retry or missing_retry:
            ObjectiveService._emit_scheduler_progress(
                progress_callback,
                0.38,
                (
                    "Exact objective scheduling attempt 2 still has problems: "
                    f"{len(issues_retry)} invalid-session issues, {len(missing_retry)} uncovered urgent tasks"
                ),
            )
        else:
            ObjectiveService._emit_scheduler_progress(
                progress_callback,
                0.38,
                f"Exact objective scheduling attempt 2 passed validation with {len(valid_retry)} sessions covering all {len(covered_retry)} urgent tasks",
            )
        return valid_retry

    @staticmethod
    def _session_blueprints_for_window(
        objectives: Sequence[Objective],
        *,
        hard_events: Sequence[dict[str, Any]],
        window_start: datetime,
        window_end: datetime,
        model: str | None = None,
    ) -> list[SessionPlan]:
        objective_index = {str(objective.id): objective for objective in objectives}
        objective_payload: list[dict[str, Any]] = []
        urgent_task_ids: set[str] = set()
        for objective in objectives:
            relevant_tasks = ObjectiveService._relevant_tasks_for_window(objective, window_start, window_end)
            if not relevant_tasks and not (objective.deadline_at and objective.deadline_at <= window_end):
                continue
            for task in relevant_tasks:
                urgent_task_ids.add(str(task.id))
            objective_payload.append(
                {
                    "id": str(objective.id),
                    "title": objective.title,
                    "description": objective.description,
                    "deadline_at": objective.deadline_at.isoformat() if objective.deadline_at else None,
                    "priority": objective.priority,
                    "remaining_effort_minutes": objective.remaining_effort_minutes,
                    "estimated_effort_minutes": objective.estimated_effort_minutes,
                    "source": ObjectiveService._objective_source(objective),
                    "notes": objective.notes,
                    "tasks": [
                        {
                            "id": str(task.id),
                            "title": task.title,
                            "description": task.description,
                            "status": task.status,
                            "due_at": task.due_at.isoformat() if task.due_at else None,
                            "estimated_effort_minutes": task.estimated_effort_minutes,
                            "remaining_effort_minutes": task.remaining_effort_minutes,
                        }
                        for task in relevant_tasks
                    ],
                    "recent_logs": ObjectiveService._recent_logs_for_objective(objective),
                }
            )

        if not objective_payload:
            return []

        model_name = model or ModelConfigService.get_soft_planner_model()
        provider = resolve_provider(model_name)
        prompt = (
            "You are planning study/work soft-event sessions for the next 14 days.\n"
            "You receive timed hard calendar events and active objectives with actionable tasks.\n"
            "Only plan objectives whose objective deadline or task deadline falls within the scheduling window.\n"
            "Skip everything else completely.\n"
            "Return JSON only with keys: sessions, summary.\n"
            "Each session must include: objective_id, title, description, notes, preferred_minutes, min_minutes, priority, task_ids.\n"
            "Rules:\n"
            "- A session may correspond to multiple tasks.\n"
            "- A difficult task may appear in multiple sessions.\n"
            "- Every task due within the window MUST appear in at least one session.\n"
            "- If time is tight, assume tasks can be compressed somewhat.\n"
            "- In genuinely dire cases you may rely on late-night work or an all-nighter, but keep that rare and place it on the least harmful day.\n"
            "- Use the hard-event load to decide which objectives deserve more or fewer sessions.\n"
            "- Prefer concise, concrete session titles and notes.\n"
            "- preferred_minutes must be >= min_minutes and both must be positive integers.\n"
            "- Keep descriptions and notes plain text.\n"
        )
        payload = {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "hard_events": list(hard_events),
            "objectives": objective_payload,
        }

        sessions_raw: list[dict[str, Any]] = []
        try:
            if provider == "openai":
                resp = get_client("openai").responses.create(
                    model=model_name,
                    input=[
                        {"role": "developer", "content": [{"type": "input_text", "text": prompt}]},
                        {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload, default=str)}]},
                    ],
                    text={"format": {"type": "json_object"}, "verbosity": "low"},
                    reasoning={"effort": "medium"},
                    store=False,
                    timeout=120,
                )
                usage_obj = getattr(resp, "usage", None)
                if usage_obj:
                    UsageService.log_usage(
                        source="objective_session_blueprints",
                        model=model_name,
                        cache_mode=ModelConfigService.get_cache_mode(),
                        usage=usage_obj,
                        job=None,
                    )
                raw = getattr(resp, "output_text", "") or "{}"
                data = json.loads(raw)
            else:
                resp = get_client("xai").chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(payload, default=str)},
                    ],
                    response_format={"type": "json_object"},
                )
                raw = "{}"
                if getattr(resp, "choices", None):
                    raw = resp.choices[0].message.content or "{}"  # type: ignore[assignment]
                data = json.loads(raw)
            sessions_raw = data.get("sessions") if isinstance(data.get("sessions"), list) else []
        except Exception:
            sessions_raw = []

        plans: list[SessionPlan] = []
        covered_urgent_tasks: set[str] = set()
        for item in sessions_raw:
            if not isinstance(item, dict):
                continue
            objective_id = str(item.get("objective_id") or "").strip()
            objective = objective_index.get(objective_id)
            if objective is None:
                continue
            valid_task_ids = {str(task.id) for task in ObjectiveService._select_actionable_tasks(objective)}
            task_ids = ObjectiveService._normalize_session_task_ids(
                objective,
                item.get("task_ids") if isinstance(item.get("task_ids"), list) else [],
                valid_task_ids,
            )
            covered_urgent_tasks.update(task_id for task_id in task_ids if task_id in urgent_task_ids)
            preferred = max(int(item.get("preferred_minutes") or ObjectiveService._preferred_minutes_for_objective(objective)), MIN_SESSION_MINUTES)
            minimum = max(int(item.get("min_minutes") or min(preferred, max(preferred // 2, MIN_SESSION_MINUTES))), 1)
            minimum = min(minimum, preferred)
            notes = ObjectiveService._session_notes_for_objective(
                objective,
                task_ids,
                extra_notes=str(item.get("notes") or ""),
            )
            plans.append(
                SessionPlan(
                    title=ObjectiveService._first_nonempty(item.get("title"), objective.title)[:255],
                    description=ObjectiveService._first_nonempty(item.get("description"), objective.description, f"Work on {objective.title}"),
                    notes=notes,
                    preferred_minutes=preferred,
                    min_minutes=minimum,
                    soft_deadline=objective.deadline_at,
                    hard_deadline=objective.deadline_at,
                    priority=max(int(item.get("priority") or objective.priority or 0), 0),
                    task_ids=task_ids,
                    metadata={
                        "source": ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
                        "objective_id": str(objective.id),
                        "objective_source": ObjectiveService._objective_source(objective),
                        "task_ids": task_ids,
                        "planner_mode": "model_window_blueprint",
                    },
                )
            )

        if urgent_task_ids - covered_urgent_tasks:
            for objective in objectives:
                relevant_tasks = ObjectiveService._relevant_tasks_for_window(objective, window_start, window_end)
                remaining_task_ids = [
                    str(task.id)
                    for task in relevant_tasks
                    if str(task.id) in urgent_task_ids - covered_urgent_tasks
                ]
                if not remaining_task_ids:
                    continue
                notes = ObjectiveService._session_notes_for_objective(
                    objective,
                    remaining_task_ids,
                    extra_notes="Fallback session added because these urgent tasks still required explicit coverage.",
                )
                plans.append(
                    SessionPlan(
                        title=f"{objective.title} — Urgent Coverage"[:255],
                        description=objective.description or f"Cover urgent work for {objective.title}",
                        notes=notes,
                        preferred_minutes=max(ObjectiveService._preferred_minutes_for_objective(objective), MIN_SESSION_MINUTES),
                        min_minutes=MIN_SESSION_MINUTES,
                        soft_deadline=objective.deadline_at,
                        hard_deadline=objective.deadline_at,
                        priority=max(int(objective.priority or 0), 0) + 10,
                        task_ids=remaining_task_ids,
                        metadata={
                            "source": ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
                            "objective_id": str(objective.id),
                            "objective_source": ObjectiveService._objective_source(objective),
                            "task_ids": remaining_task_ids,
                            "planner_mode": "urgent_fallback_coverage",
                        },
                    )
                )
                covered_urgent_tasks.update(remaining_task_ids)

        if plans:
            return plans

        fallback: list[SessionPlan] = []
        for objective in objectives:
            if ObjectiveService._should_schedule_objective(objective, window_start, window_end):
                fallback.extend(ObjectiveService._build_sessions_for_objective(objective))
        return fallback

    @staticmethod
    def _build_assignment_sessions(assignment) -> list[SessionPlan]:
        objective = assignment.objective
        tasks = ObjectiveService._select_actionable_tasks(objective)
        remaining = objective.remaining_effort_minutes or objective.estimated_effort_minutes or DEFAULT_ASSIGNMENT_SESSION_MINUTES
        preferred = DEFAULT_ASSIGNMENT_SESSION_MINUTES
        session_count = max(int(ceil(max(remaining, MIN_SESSION_MINUTES) / preferred)), 1)
        if assignment.session_count:
            session_count = max(session_count, int(assignment.session_count))
        task_groups: list[list[ObjectiveTask]] = [[] for _ in range(session_count)]
        if tasks:
            for idx, task in enumerate(tasks):
                task_groups[idx % session_count].append(task)
        sessions: list[SessionPlan] = []
        for index in range(session_count):
            group = task_groups[index]
            step_lines = [
                f"- {task.title}: {task.description}".strip(": ")
                for task in group
            ]
            notes = [
                f"Assignment: {assignment.title}",
                f"Session {index + 1} of {session_count}",
            ]
            if step_lines:
                notes.append("Tasks:\n" + "\n".join(step_lines))
            if assignment.material_text:
                notes.append(f"Material:\n{assignment.material_text[:700]}...")
            sessions.append(
                SessionPlan(
                    title=f"{assignment.title} — Session {index + 1}",
                    description=objective.description or f"Work on {assignment.title}",
                    notes="\n\n".join(notes).strip(),
                    preferred_minutes=preferred,
                    min_minutes=60,
                    soft_deadline=assignment.due_at,
                    hard_deadline=assignment.due_at,
                    priority=max(objective.priority, 1),
                    task_ids=[str(task.id) for task in group],
                    metadata={
                        "source": ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
                        "study_assignment_id": str(assignment.id),
                        "objective_id": str(objective.id),
                        "session_number": index + 1,
                        "session_count": session_count,
                    },
                )
            )
        return sessions

    @staticmethod
    def _link_soft_event(soft_event: SoftEvent, objective: Objective, task_ids: Sequence[str]) -> None:
        SoftEventObjective.objects.update_or_create(
            soft_event=soft_event,
            objective=objective,
            defaults={"role": SoftEventObjective.ROLE_PRIMARY},
        )
        existing_links = set(SoftEventTask.objects.filter(soft_event=soft_event).values_list("task_id", flat=True))
        desired_links = {task_id for task_id in task_ids}
        stale_ids = existing_links - desired_links
        if stale_ids:
            SoftEventTask.objects.filter(soft_event=soft_event, task_id__in=stale_ids).delete()
        new_ids = desired_links - existing_links
        for task_id in new_ids:
            SoftEventTask.objects.create(soft_event=soft_event, task_id=task_id)

    @staticmethod
    @transaction.atomic
    def replace_soft_events_for_objective(
        objective: Objective,
        session_plans: Sequence[SessionPlan],
        *,
        clear_only_metadata_source: str = OBJECTIVE_SOFT_EVENT_SOURCE,
    ) -> list[str]:
        existing_events = list(
            SoftEvent.objects.filter(
                objective_links__objective=objective,
                metadata__source=clear_only_metadata_source,
            ).distinct()
        )
        existing_by_session = {
            int(event.metadata.get("session_number") or 0): event
            for event in existing_events
            if isinstance(event.metadata, dict)
        }
        keep_ids: set[str] = set()
        created_ids: list[str] = []
        for plan in session_plans:
            session_number = int(plan.metadata.get("session_number") or 0)
            soft_event = existing_by_session.get(session_number)
            if soft_event is None:
                soft_event = SoftEvent.objects.create(
                    title=plan.title,
                    description=plan.description,
                    notes=plan.notes,
                    preferred_duration_minutes=plan.preferred_minutes,
                    min_duration_minutes=plan.min_minutes,
                    soft_deadline=plan.soft_deadline,
                    hard_deadline=plan.hard_deadline,
                    priority=plan.priority,
                    status=SoftEvent.STATUS_ACTIVE,
                    metadata=plan.metadata,
                    chat=objective.chat,
                )
            else:
                soft_event.title = plan.title
                soft_event.description = plan.description
                soft_event.notes = plan.notes
                soft_event.preferred_duration_minutes = plan.preferred_minutes
                soft_event.min_duration_minutes = plan.min_minutes
                soft_event.soft_deadline = plan.soft_deadline
                soft_event.hard_deadline = plan.hard_deadline
                soft_event.priority = plan.priority
                soft_event.status = SoftEvent.STATUS_ACTIVE
                soft_event.metadata = plan.metadata
                soft_event.chat = objective.chat
                soft_event.save(
                    update_fields=[
                        "title",
                        "description",
                        "notes",
                        "preferred_duration_minutes",
                        "min_duration_minutes",
                        "soft_deadline",
                        "hard_deadline",
                        "priority",
                        "status",
                        "metadata",
                        "chat",
                        "updated_at",
                    ]
                )
            ObjectiveService._link_soft_event(soft_event, objective, plan.task_ids)
            keep_ids.add(str(soft_event.id))
            created_ids.append(str(soft_event.id))

        stale_events = [event for event in existing_events if str(event.id) not in keep_ids]
        stale_event_ids = [event.id for event in stale_events]
        if stale_event_ids:
            SoftEventSlot.objects.filter(
                soft_event_id__in=stale_event_ids,
                status__in=[SoftEventSlot.STATUS_PLANNED, SoftEventSlot.STATUS_DEFERRED],
            ).update(
                status=SoftEventSlot.STATUS_CANCELED,
                rationale="Canceled because objective planning was regenerated.",
                updated_at=timezone.now(),
            )
            SoftEvent.objects.filter(id__in=stale_event_ids).update(
                status=SoftEvent.STATUS_ARCHIVED,
                updated_at=timezone.now(),
            )
        return created_ids

    @staticmethod
    @transaction.atomic
    def create_soft_events_from_session_plans(session_plans: Sequence[SessionPlan]) -> dict[str, Any]:
        objective_ids: set[str] = set()
        for plan in session_plans:
            objective_id = str((plan.metadata or {}).get("objective_id") or "").strip()
            if objective_id:
                objective_ids.add(objective_id)
        objective_map = {
            str(objective.id): objective
            for objective in Objective.objects.filter(id__in=list(objective_ids)).select_related("chat")
        }
        created_ids: list[str] = []
        created_slot_ids: list[str] = []
        for index, plan in enumerate(session_plans, start=1):
            metadata = dict(plan.metadata or {})
            objective_id = str(metadata.get("objective_id") or "").strip()
            objective = objective_map.get(objective_id)
            if objective is None:
                continue
            metadata["session_number"] = index
            soft_event = SoftEvent.objects.create(
                title=plan.title,
                description=plan.description,
                notes=plan.notes,
                preferred_duration_minutes=max(int(plan.preferred_minutes or MIN_SESSION_MINUTES), 1),
                min_duration_minutes=max(int(plan.min_minutes or MIN_SESSION_MINUTES), 1),
                soft_deadline=plan.soft_deadline,
                hard_deadline=plan.hard_deadline,
                priority=max(int(plan.priority or 0), 0),
                status=SoftEvent.STATUS_ACTIVE,
                metadata=metadata,
                chat=objective.chat,
            )
            ObjectiveService._link_soft_event(soft_event, objective, plan.task_ids)
            created_ids.append(str(soft_event.id))
            if plan.start_at and plan.end_at:
                slot = SoftEventSlot.objects.create(
                    soft_event=soft_event,
                    start_at=plan.start_at,
                    end_at=plan.end_at,
                    notify_at=plan.notify_at,
                    rationale=plan.rationale or soft_event.title,
                    metadata={
                        "source": ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
                        "objective_id": str(objective.id),
                        "task_ids": list(plan.task_ids),
                    },
                )
                created_slot_ids.append(str(slot.id))
        return {
            "soft_event_ids": created_ids,
            "slot_ids": created_slot_ids,
            "created_soft_events": len(created_ids),
            "created_slots": len(created_slot_ids),
        }

    @staticmethod
    @transaction.atomic
    def archive_objective_soft_events(objective: Objective, *, metadata_source: str = "objective_planner") -> int:
        soft_events = SoftEvent.objects.filter(
            objective_links__objective=objective,
            metadata__source=metadata_source,
        ).distinct()
        soft_event_ids = list(soft_events.values_list("id", flat=True))
        if soft_event_ids:
            SoftEventSlot.objects.filter(
                soft_event_id__in=soft_event_ids,
                status__in=[SoftEventSlot.STATUS_PLANNED, SoftEventSlot.STATUS_DEFERRED],
            ).update(
                status=SoftEventSlot.STATUS_CANCELED,
                rationale="Canceled because the linked objective was completed.",
                updated_at=timezone.now(),
            )
        return soft_events.exclude(status=SoftEvent.STATUS_ARCHIVED).update(
            status=SoftEvent.STATUS_ARCHIVED,
            updated_at=timezone.now(),
        )

    @staticmethod
    def _sync_assignment_refs(objective: Objective, soft_event_ids: Sequence[str]) -> None:
        try:
            assignment = objective.study_assignment
        except Exception:
            return
        desired = list(soft_event_ids)
        if (assignment.soft_event_refs or []) != desired:
            assignment.soft_event_refs = desired
            assignment.save(update_fields=["soft_event_refs", "updated_at"])

    @staticmethod
    def sync_objective_soft_events_for_window(
        window_start: datetime,
        window_end: datetime,
        *,
        planner_note: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> dict[str, int]:
        objectives, relevant, session_plans = ObjectiveService._prepare_objective_window_plan(
            window_start,
            window_end,
            planner_note=planner_note,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        return ObjectiveService._apply_objective_window_plan(
            objectives=objectives,
            relevant=relevant,
            session_plans=session_plans,
            window_start=window_start,
            window_end=window_end,
            progress_callback=progress_callback,
        )

    @staticmethod
    def _prepare_objective_window_plan(
        window_start: datetime,
        window_end: datetime,
        *,
        planner_note: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> tuple[list[Objective], list[Objective], list[SessionPlan]]:
        ObjectiveService._ensure_not_canceled(cancel_check)
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            0.08,
            "Fetching hard calendar events for objective replanning",
        )
        hard_events = list_events(
            time_min=window_start.isoformat(),
            time_max=window_end.isoformat(),
            max_results=2500,
        ).get("events", [])
        ObjectiveService._ensure_not_canceled(cancel_check)
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            0.14,
            "Loading active objectives and urgent tasks in the planning window",
        )
        objectives = list(
            Objective.objects.all().select_related("parent", "chat").prefetch_related("tasks")
        )
        relevant = [
            objective
            for objective in objectives
            if ObjectiveService._should_schedule_objective(objective, window_start, window_end)
        ]
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            0.18,
            f"Preparing exact schedule for {len(relevant)} relevant objective(s)",
        )
        session_plans = ObjectiveService._scheduled_session_plans_for_window(
            relevant,
            hard_events=hard_events,
            window_start=window_start,
            window_end=window_end,
            planner_note=planner_note,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        return objectives, relevant, session_plans

    @staticmethod
    @transaction.atomic
    def _apply_objective_window_plan(
        *,
        objectives: Sequence[Objective],
        relevant: Sequence[Objective],
        session_plans: Sequence[SessionPlan],
        window_start: datetime,
        window_end: datetime,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict[str, int]:
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            0.42,
            "Purging previous objective-generated soft events",
        )
        purge_stats = ObjectiveService.purge_objective_soft_events_for_window(window_start, window_end)
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            0.5,
            "Clearing assigned slots from non-objective soft events",
        )
        unassign_stats = ObjectiveService.unassign_nonobjective_soft_event_slots(window_start)
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            0.58,
            f"Creating {len(session_plans)} objective session soft event(s) with exact slots",
        )
        create_stats = ObjectiveService.create_soft_events_from_session_plans(session_plans)
        soft_event_ids = create_stats["soft_event_ids"]
        refs_by_objective: dict[str, list[str]] = {}
        for session_plan, soft_event_id in zip(session_plans, soft_event_ids):
            objective_id = str((session_plan.metadata or {}).get("objective_id") or "").strip()
            if objective_id:
                refs_by_objective.setdefault(objective_id, []).append(soft_event_id)
        for objective in objectives:
            ObjectiveService._sync_assignment_refs(objective, refs_by_objective.get(str(objective.id), []))
        ObjectiveService._emit_scheduler_progress(
            progress_callback,
            0.66,
            f"Applied {create_stats['created_soft_events']} objective soft event(s) and {create_stats['created_slots']} slot(s)",
        )
        return {
            **purge_stats,
            **unassign_stats,
            "scanned_objectives": len(objectives),
            "relevant_objectives": len(relevant),
            "planned_soft_events": len(soft_event_ids),
            "planned_slots": create_stats["created_slots"],
        }

    @staticmethod
    @transaction.atomic
    def purge_objective_soft_events_for_window(window_start: datetime, window_end: datetime) -> dict[str, int]:
        soft_events = list(
            SoftEvent.objects.filter(
                objective_links__isnull=False,
                metadata__source=ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
                status=SoftEvent.STATUS_ACTIVE,
            ).distinct()
        )
        if not soft_events:
            return {"purged_soft_events": 0, "canceled_slots": 0}

        soft_event_ids = [event.id for event in soft_events]
        canceled_slots = SoftEventSlot.objects.filter(
            soft_event_id__in=soft_event_ids,
            end_at__gte=window_start,
            status__in=ObjectiveService.SLOT_UNASSIGN_STATUSES,
        ).update(
            status=SoftEventSlot.STATUS_CANCELED,
            rationale="Canceled because the objective scheduler regenerated the 2-week plan.",
            updated_at=timezone.now(),
        )
        purged_soft_events = SoftEvent.objects.filter(id__in=soft_event_ids).update(
            status=SoftEvent.STATUS_ARCHIVED,
            updated_at=timezone.now(),
        )
        return {
            "purged_soft_events": purged_soft_events,
            "canceled_slots": canceled_slots,
        }

    @staticmethod
    @transaction.atomic
    def unassign_nonobjective_soft_event_slots(window_start: datetime) -> dict[str, int]:
        slots_qs = SoftEventSlot.objects.filter(
            end_at__gte=window_start,
            status__in=ObjectiveService.SLOT_UNASSIGN_STATUSES,
        ).exclude(soft_event__metadata__source=ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE)
        unassigned_slots = slots_qs.update(
            status=SoftEventSlot.STATUS_CANCELED,
            rationale="Canceled so the planner can reassign this soft event from scratch.",
            updated_at=timezone.now(),
        )
        return {"unassigned_slots": unassigned_slots}

    @staticmethod
    def rebuild_objective_soft_events_for_window(
        window_start: datetime,
        window_end: datetime,
        *,
        planner_note: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> dict[str, int]:
        objectives, relevant, session_plans = ObjectiveService._prepare_objective_window_plan(
            window_start,
            window_end,
            planner_note=planner_note,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        return ObjectiveService._apply_objective_window_plan(
            objectives=objectives,
            relevant=relevant,
            session_plans=session_plans,
            window_start=window_start,
            window_end=window_end,
            progress_callback=progress_callback,
        )

    @staticmethod
    @transaction.atomic
    def mark_slot_outcome(
        slot_id: str,
        *,
        outcome: str,
        reason: str = "",
        minutes_spent: Optional[int] = None,
        completed_task_ids: Optional[Sequence[str]] = None,
        create_log: bool = True,
    ) -> dict[str, Any]:
        slot = SoftEventSlot.objects.select_related("soft_event").get(id=slot_id)
        normalized = str(outcome or "").strip().lower()
        if normalized in {"completed", "done", "executed", "performed"}:
            next_status = SoftEventSlot.STATUS_COMPLETED
            log_kind = ObjectiveLog.KIND_WORK
        elif normalized in {"skipped", "missed", "not_performed", "not_executed"}:
            next_status = SoftEventSlot.STATUS_SKIPPED
            log_kind = ObjectiveLog.KIND_BLOCKER if reason.strip() else ObjectiveLog.KIND_NOTE
        else:
            raise ValueError("Unsupported slot outcome")

        linked_task_ids = set(
            str(task_id)
            for task_id in SoftEventTask.objects.filter(soft_event=slot.soft_event).values_list("task_id", flat=True)
        )
        requested_task_ids = [str(task_id) for task_id in (completed_task_ids or [])]
        resolved_completed_task_ids = [task_id for task_id in requested_task_ids if task_id in linked_task_ids]

        metadata = dict(slot.metadata or {})
        metadata.update(
            {
                "execution_note": reason.strip(),
                "outcome_reason": reason.strip(),
                "minutes_spent": minutes_spent,
                "completed_task_ids": resolved_completed_task_ids,
                "marked_at": timezone.now().isoformat(),
            }
        )
        slot.status = next_status
        slot.metadata = metadata
        if reason.strip():
            slot.rationale = reason.strip()
        slot.save(update_fields=["status", "metadata", "rationale", "updated_at"])

        if next_status == SoftEventSlot.STATUS_COMPLETED and resolved_completed_task_ids:
            ObjectiveTask.objects.filter(id__in=resolved_completed_task_ids).update(
                status=ObjectiveTask.STATUS_DONE,
                completed_at=timezone.now(),
                updated_at=timezone.now(),
            )

        objective_links = list(
            SoftEventObjective.objects.filter(soft_event=slot.soft_event)
            .select_related("objective")
            .order_by("role", "created_at")
        )
        for link in objective_links:
            link.objective.remaining_effort_minutes = ObjectiveService._sum_child_remaining(link.objective)
            link.objective.save(update_fields=["remaining_effort_minutes", "updated_at"])

        if create_log:
            task_map = {
                str(task.id): task
                for task in ObjectiveTask.objects.filter(id__in=list(linked_task_ids))
            }
            for link in objective_links:
                task = task_map.get(resolved_completed_task_ids[0]) if len(resolved_completed_task_ids) == 1 else None
                if next_status == SoftEventSlot.STATUS_COMPLETED:
                    text = reason.strip() or f"Completed scheduled session: {slot.soft_event.title}"
                else:
                    text = reason.strip() or f"Scheduled session was not performed: {slot.soft_event.title}"
                ObjectiveLog.objects.create(
                    objective=link.objective,
                    task=task,
                    kind=log_kind,
                    text=text,
                    minutes_spent=minutes_spent if next_status == SoftEventSlot.STATUS_COMPLETED else None,
                    metadata={
                        "source": "soft_slot_outcome",
                        "slot_id": str(slot.id),
                        "soft_event_id": str(slot.soft_event_id),
                        "soft_event_title": slot.soft_event.title,
                        "outcome": next_status,
                        "linked_task_ids": sorted(linked_task_ids),
                        "completed_task_ids": resolved_completed_task_ids,
                    },
                )

        return {
            "slot_id": str(slot.id),
            "soft_event_id": str(slot.soft_event_id),
            "status": slot.status,
            "linked_task_ids": sorted(linked_task_ids),
            "completed_task_ids": resolved_completed_task_ids,
        }

    @staticmethod
    def scheduler_snapshot(window_start: datetime, window_end: datetime) -> list[dict[str, Any]]:
        snapshot: list[dict[str, Any]] = []
        _matched_by_event, matched_by_task = ObjectiveService._matched_hard_event_links(window_start, window_end)
        for objective in Objective.objects.all().order_by("deadline_at", "-priority", "created_at"):
            if not ObjectiveService._should_schedule_objective(objective, window_start, window_end):
                continue
            tasks = ObjectiveService._select_actionable_tasks(objective)
            hard_covered_task_ids = ObjectiveService._task_ids_covered_by_hard_events(
                tasks,
                window_start=window_start,
                window_end=window_end,
                matched_by_task=matched_by_task,
            )
            tasks = [task for task in tasks if str(task.id) not in hard_covered_task_ids]
            snapshot.append(
                {
                    "id": str(objective.id),
                    "title": objective.title,
                    "deadline_at": objective.deadline_at.isoformat() if objective.deadline_at else None,
                    "priority": objective.priority,
                    "remaining_effort_minutes": objective.remaining_effort_minutes,
                    "estimated_effort_minutes": objective.estimated_effort_minutes,
                    "source": ObjectiveService._objective_source(objective),
                    "notes": objective.notes,
                    "tasks": [
                        {
                            "id": str(task.id),
                            "title": task.title,
                            "status": task.status,
                            "due_at": task.due_at.isoformat() if task.due_at else None,
                            "estimated_effort_minutes": task.estimated_effort_minutes,
                            "remaining_effort_minutes": task.remaining_effort_minutes,
                            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                        }
                        for task in tasks
                    ],
                    "recent_logs": ObjectiveService._recent_logs_for_objective(objective),
                    "upcoming_exams": ObjectiveService._upcoming_exams_for_objective(objective),
                    "hard_scheduled_task_ids": sorted(hard_covered_task_ids),
                }
            )
        return snapshot

    @staticmethod
    def coverage_snapshot(
        window_start: datetime,
        window_end: datetime,
        *,
        hard_events: Optional[Sequence[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        tasks = list(
            ObjectiveTask.objects.select_related("objective")
            .exclude(status__in=[ObjectiveTask.STATUS_DONE, ObjectiveTask.STATUS_CANCELED, ObjectiveTask.STATUS_BLOCKED])
            .filter(
                objective__status=Objective.STATUS_ACTIVE,
                due_at__isnull=False,
                due_at__gte=window_start,
                due_at__lte=window_end,
            )
            .order_by("due_at", "objective__title", "sort_order", "created_at")
        )
        items: list[dict[str, Any]] = []
        summary = {"total": 0, "covered": 0, "uncovered": 0}
        _matched_by_event, matched_by_task = ObjectiveService._matched_hard_event_links(
            window_start,
            window_end,
            hard_events=hard_events,
        )
        for task in tasks:
            link_qs = SoftEventTask.objects.filter(task=task)
            soft_event_ids = list(link_qs.values_list("soft_event_id", flat=True))
            slot_qs = SoftEventSlot.objects.filter(
                soft_event_id__in=soft_event_ids,
                start_at__lt=window_end,
                status__in=[
                    SoftEventSlot.STATUS_PLANNED,
                    SoftEventSlot.STATUS_PROMOTED,
                    SoftEventSlot.STATUS_COMPLETED,
                ],
            )
            if task.due_at:
                slot_qs = slot_qs.filter(start_at__lte=task.due_at)
            scheduled_minutes = 0
            slot_ids: list[str] = []
            for slot in slot_qs:
                scheduled_minutes += max(int((slot.end_at - slot.start_at).total_seconds() // 60), 0)
                slot_ids.append(str(slot.id))
            hard_event_refs: list[dict[str, Any]] = []
            deadline = task.due_at or window_end
            for event in matched_by_task.get(str(task.id), []):
                start, end = ObjectiveService._event_bounds(event)
                if not start or not end or start > deadline:
                    continue
                scheduled_minutes += max(int((end - start).total_seconds() // 60), 0)
                hard_event_refs.append(
                    {
                        "event_id": str(event.get("id") or ""),
                        "title": str(event.get("summary") or "(no title)"),
                        "start": event.get("start"),
                        "end": event.get("end"),
                    }
                )
            coverage_state = "covered" if slot_ids or hard_event_refs else "uncovered"
            summary["total"] += 1
            summary[coverage_state] += 1
            items.append(
                {
                    "task_id": str(task.id),
                    "objective_id": str(task.objective_id),
                    "objective_title": task.objective.title,
                    "task_title": task.title,
                    "due_at": task.due_at.isoformat() if task.due_at else None,
                    "required_minutes": task.remaining_effort_minutes or task.estimated_effort_minutes or 0,
                    "scheduled_minutes": scheduled_minutes,
                    "coverage_state": coverage_state,
                    "slot_ids": slot_ids,
                    "hard_event_refs": hard_event_refs,
                }
            )
        return {"summary": summary, "items": items}

    @staticmethod
    def plan_soft_event_window(window_start: datetime, window_end: datetime) -> tuple[int, int]:
        hard_events = list_events(
            time_min=window_start.isoformat(),
            time_max=window_end.isoformat(),
            max_results=2500,
        ).get("events", [])
        soft_state = collect_window_state(window_start, window_end)
        soft_state["objective_inputs"] = ObjectiveService.scheduler_snapshot(window_start, window_end)
        actions, trace_id = plan_soft_window(
            hard_events=hard_events,
            soft_state=soft_state,
            window_start=window_start,
            window_end=window_end,
        )
        return SoftEventService.apply_planner_actions(actions, planner_trace_id=trace_id)

    @staticmethod
    def plan_assignment_objective(assignment, *, window_days: int = 14) -> list[str]:
        ObjectiveService.ensure_assignment_objective(assignment)
        window_start = timezone.now()
        window_end = min(assignment.due_at, window_start + timedelta(days=max(window_days, 1)))
        ObjectiveService.sync_objective_soft_events_for_window(window_start, window_end)
        try:
            assignment.refresh_from_db(fields=["soft_event_refs"])
        except Exception:
            pass
        return list(assignment.soft_event_refs or [])
