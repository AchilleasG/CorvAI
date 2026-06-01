from __future__ import annotations

from typing import Optional
from uuid import UUID
from ninja import Schema
from orchestration.models import Job


class JobOut(Schema):
    id: UUID
    status: str
    user_visible_summary: str
    progress: float
    module_slug: Optional[str] = None
    active_function: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    cancel_requested: Optional[bool] = None
    error_summary: Optional[str] = None

    @staticmethod
    def from_model(job: Job) -> "JobOut":
        return JobOut(
            id=job.id,
            status=job.status,
            user_visible_summary=job.user_visible_summary or "",
            progress=job.progress,
            module_slug=job.module.slug if job.module else None,
            active_function=job.active_function.manifest_id if job.active_function else None,
            metadata=job.metadata,
            created_at=job.created_at.isoformat() if job.created_at else None,
            updated_at=job.updated_at.isoformat() if job.updated_at else None,
            cancel_requested=job.cancel_requested,
            error_summary=job.error_summary or None,
        )


class ScheduledTaskOut(Schema):
    id: UUID
    prompt: str
    recurrence: str
    start_at: Optional[str] = None
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    status: str
    is_running: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @staticmethod
    def from_model(task) -> "ScheduledTaskOut":
        return ScheduledTaskOut(
            id=task.id,
            prompt=task.prompt,
            recurrence=task.recurrence,
            start_at=task.start_at.isoformat() if task.start_at else None,
            next_run_at=task.next_run_at.isoformat() if task.next_run_at else None,
            last_run_at=task.last_run_at.isoformat() if task.last_run_at else None,
            status=task.status,
            is_running=task.is_running,
            created_at=task.created_at.isoformat() if task.created_at else None,
            updated_at=task.updated_at.isoformat() if task.updated_at else None,
        )


class UpdateScheduledTaskIn(Schema):
    prompt: Optional[str] = None
    recurrence: Optional[str] = None
    start_at: Optional[str] = None
    status: Optional[str] = None


class ScheduledTaskLogOut(Schema):
    id: UUID
    role: str
    level: str
    message: str
    created_at: Optional[str] = None


class ScheduledTaskRunOut(Schema):
    id: UUID
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    summary: str
    error_summary: str
    log_entries: list[ScheduledTaskLogOut]


class PushTokenOut(Schema):
    id: UUID
    token: str
    platform: str
    created_at: Optional[str] = None
    last_seen_at: Optional[str] = None


class UserMessageOut(Schema):
    id: UUID
    title: str
    body: str
    kind: str
    read_at: Optional[str] = None
    created_at: Optional[str] = None


class CallTranscriptEntryOut(Schema):
    id: UUID
    role: str
    content: str
    created_at: Optional[str] = None
    end_call: Optional[bool] = None


class CallSessionOut(Schema):
    id: UUID
    goal: str
    status: str
    scheduled_for: Optional[str] = None
    ringing_started_at: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    summary: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ObjectiveTaskOut(Schema):
    id: UUID
    objective_id: UUID
    title: str
    description: str
    status: str
    estimated_effort_minutes: Optional[int] = None
    remaining_effort_minutes: Optional[int] = None
    due_at: Optional[str] = None
    sort_order: int
    metadata: Optional[dict] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @staticmethod
    def from_model(task) -> "ObjectiveTaskOut":
        return ObjectiveTaskOut(
            id=task.id,
            objective_id=task.objective_id,
            title=task.title,
            description=task.description,
            status=task.status,
            estimated_effort_minutes=task.estimated_effort_minutes,
            remaining_effort_minutes=task.remaining_effort_minutes,
            due_at=task.due_at.isoformat() if task.due_at else None,
            sort_order=task.sort_order,
            metadata=task.metadata or {},
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
            created_at=task.created_at.isoformat() if task.created_at else None,
            updated_at=task.updated_at.isoformat() if task.updated_at else None,
        )


class ObjectiveLogOut(Schema):
    id: UUID
    objective_id: UUID
    task_id: Optional[UUID] = None
    kind: str
    text: str
    minutes_spent: Optional[int] = None
    logged_at: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: Optional[str] = None

    @staticmethod
    def from_model(log) -> "ObjectiveLogOut":
        return ObjectiveLogOut(
            id=log.id,
            objective_id=log.objective_id,
            task_id=log.task_id,
            kind=log.kind,
            text=log.text,
            minutes_spent=log.minutes_spent,
            logged_at=log.logged_at.isoformat() if log.logged_at else None,
            metadata=log.metadata or {},
            created_at=log.created_at.isoformat() if log.created_at else None,
        )


class ObjectiveOut(Schema):
    id: UUID
    parent_id: Optional[UUID] = None
    title: str
    description: str
    status: str
    deadline_at: Optional[str] = None
    estimated_effort_minutes: Optional[int] = None
    remaining_effort_minutes: Optional[int] = None
    priority: int
    notes: str
    metadata: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    tasks: list[ObjectiveTaskOut] = []
    logs: list[ObjectiveLogOut] = []
    children: list["ObjectiveOut"] = []

    @staticmethod
    def from_model(objective, *, include_children: bool = False, include_logs: bool = True) -> "ObjectiveOut":
        tasks = [ObjectiveTaskOut.from_model(task) for task in objective.tasks.all().order_by("sort_order", "created_at")]
        logs = []
        if include_logs:
            logs = [ObjectiveLogOut.from_model(log) for log in objective.logs.all().order_by("-logged_at", "-created_at")[:20]]
        children = []
        if include_children:
            children = [
                ObjectiveOut.from_model(child, include_children=True, include_logs=False)
                for child in objective.children.all().order_by("deadline_at", "-priority", "created_at")
            ]
        return ObjectiveOut(
            id=objective.id,
            parent_id=objective.parent_id,
            title=objective.title,
            description=objective.description,
            status=objective.status,
            deadline_at=objective.deadline_at.isoformat() if objective.deadline_at else None,
            estimated_effort_minutes=objective.estimated_effort_minutes,
            remaining_effort_minutes=objective.remaining_effort_minutes,
            priority=objective.priority,
            notes=objective.notes,
            metadata=objective.metadata or {},
            created_at=objective.created_at.isoformat() if objective.created_at else None,
            updated_at=objective.updated_at.isoformat() if objective.updated_at else None,
            completed_at=objective.completed_at.isoformat() if objective.completed_at else None,
            tasks=tasks,
            logs=logs,
            children=children,
        )


ObjectiveOut.model_rebuild()
