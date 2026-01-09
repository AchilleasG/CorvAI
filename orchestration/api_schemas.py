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
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    cancel_requested: Optional[bool] = None

    @staticmethod
    def from_model(job: Job) -> "JobOut":
        return JobOut(
            id=job.id,
            status=job.status,
            user_visible_summary=job.user_visible_summary or "",
            progress=job.progress,
            module_slug=job.module.slug if job.module else None,
            active_function=job.active_function.manifest_id if job.active_function else None,
            created_at=job.created_at.isoformat() if job.created_at else None,
            updated_at=job.updated_at.isoformat() if job.updated_at else None,
            cancel_requested=job.cancel_requested,
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
