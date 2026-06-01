from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Iterable, Optional, Sequence

from django.db import transaction
from django.utils import timezone

from orchestration.models import (
    Objective,
    ObjectiveLog,
    ObjectiveTask,
    SoftEvent,
    SoftEventObjective,
    SoftEventSlot,
    SoftEventTask,
)
from orchestration.services import SoftEventService
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


class ObjectiveService:
    OBJECTIVE_SOFT_EVENT_SOURCE = "objective_scheduler"

    @staticmethod
    def _clean_text(value: object) -> str:
        return str(value or "").strip()

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
        tasks = ObjectiveService._select_actionable_tasks(objective)
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
    def sync_objective_soft_events_for_window(window_start: datetime, window_end: datetime) -> dict[str, int]:
        created = 0
        archived = 0
        scanned = 0
        linked_objective_ids = set(
            str(objective_id)
            for objective_id in SoftEventObjective.objects.filter(
                soft_event__metadata__source=ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE
            ).values_list("objective_id", flat=True)
        )
        objectives = list(
            Objective.objects.all().select_related("parent", "chat").prefetch_related("tasks")
        )
        relevant_ids: set[str] = set()
        for objective in objectives:
            scanned += 1
            if ObjectiveService._should_schedule_objective(objective, window_start, window_end):
                session_plans = ObjectiveService._build_sessions_for_objective(objective)
                soft_event_ids = ObjectiveService.replace_soft_events_for_objective(objective, session_plans)
                created += len(soft_event_ids)
                ObjectiveService._sync_assignment_refs(objective, soft_event_ids)
                relevant_ids.add(str(objective.id))
            else:
                ObjectiveService._sync_assignment_refs(objective, [])

        stale_ids = linked_objective_ids - relevant_ids
        for objective_id in stale_ids:
            objective = Objective.objects.filter(id=objective_id).first()
            if objective is None:
                continue
            archived += ObjectiveService.archive_objective_soft_events(
                objective,
                metadata_source=ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
            )
            ObjectiveService._sync_assignment_refs(objective, [])

        return {
            "scanned_objectives": scanned,
            "relevant_objectives": len(relevant_ids),
            "planned_soft_events": created,
            "archived_soft_events": archived,
        }

    @staticmethod
    @transaction.atomic
    def purge_objective_soft_events_for_window(window_start: datetime, window_end: datetime) -> dict[str, int]:
        soft_events = list(
            SoftEvent.objects.filter(
                metadata__source=ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
                status=SoftEvent.STATUS_ACTIVE,
            ).distinct()
        )
        if not soft_events:
            return {"purged_soft_events": 0, "canceled_slots": 0}

        soft_event_ids = [event.id for event in soft_events]
        canceled_slots = SoftEventSlot.objects.filter(
            soft_event_id__in=soft_event_ids,
            start_at__lt=window_end,
            end_at__gt=window_start,
            status__in=[SoftEventSlot.STATUS_PLANNED, SoftEventSlot.STATUS_DEFERRED],
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
    def rebuild_objective_soft_events_for_window(window_start: datetime, window_end: datetime) -> dict[str, int]:
        purge_stats = ObjectiveService.purge_objective_soft_events_for_window(window_start, window_end)
        sync_stats = ObjectiveService.sync_objective_soft_events_for_window(window_start, window_end)
        return {
            **purge_stats,
            **sync_stats,
        }

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
        for objective in Objective.objects.all().order_by("deadline_at", "-priority", "created_at"):
            if not ObjectiveService._should_schedule_objective(objective, window_start, window_end):
                continue
            tasks = ObjectiveService._select_actionable_tasks(objective)
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
                    "slot_history": ObjectiveService._slot_history_for_objective(objective),
                    "recent_logs": ObjectiveService._recent_logs_for_objective(objective),
                }
            )
        return snapshot

    @staticmethod
    def coverage_snapshot(window_start: datetime, window_end: datetime) -> dict[str, Any]:
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
        summary = {"total": 0, "covered": 0, "partial": 0, "uncovered": 0}
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
            required_minutes = task.remaining_effort_minutes or task.estimated_effort_minutes or 0
            if required_minutes > 0:
                if scheduled_minutes >= required_minutes:
                    coverage_state = "covered"
                elif scheduled_minutes > 0:
                    coverage_state = "partial"
                else:
                    coverage_state = "uncovered"
            else:
                coverage_state = "covered" if scheduled_minutes > 0 else "uncovered"
            summary["total"] += 1
            summary[coverage_state] += 1
            items.append(
                {
                    "task_id": str(task.id),
                    "objective_id": str(task.objective_id),
                    "objective_title": task.objective.title,
                    "task_title": task.title,
                    "due_at": task.due_at.isoformat() if task.due_at else None,
                    "required_minutes": required_minutes,
                    "scheduled_minutes": scheduled_minutes,
                    "missing_minutes": max(required_minutes - scheduled_minutes, 0) if required_minutes > 0 else None,
                    "coverage_state": coverage_state,
                    "slot_ids": slot_ids,
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
