from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from django.utils import timezone

from orchestration.models import ScheduledTask, ScheduledTaskRun, ScheduledTaskLogEntry
from orchestration.registry import register_function
from orchestration.scheduler import compute_next_run


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
    manifest_id="scheduled_tasks.create_task",
    module="scheduled_tasks",
    name="scheduled_tasks.create_task",
    description="Create a scheduled task that runs later via the Function Caller.",
    params_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "start_at": {"type": "string", "description": "ISO datetime when the task should first run"},
            "recurrence": {"type": "string", "description": "once|daily|weekly|monthly"},
        },
        "required": ["prompt"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "status": {"type": "string"},
            "next_run_at": {"type": "string"},
        },
    },
)
def create_task(
    prompt: str,
    start_at: Optional[str] = None,
    recurrence: str = ScheduledTask.RECURRENCE_ONCE,
):
    if recurrence not in dict(ScheduledTask.RECURRENCE_CHOICES):
        raise ValueError("Invalid recurrence value")
    start_dt = _parse_dt(start_at) or timezone.now()
    task = ScheduledTask.objects.create(
        prompt=prompt,
        recurrence=recurrence,
        start_at=start_dt,
        next_run_at=start_dt,
        status=ScheduledTask.STATUS_ACTIVE,
    )
    return {
        "id": str(task.id),
        "status": task.status,
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
    }


@register_function(
    manifest_id="scheduled_tasks.list_tasks",
    module="scheduled_tasks",
    name="scheduled_tasks.list_tasks",
    description="List scheduled tasks with optional status filter.",
    params_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "active|paused|completed"},
        },
    },
)
def list_tasks(status: Optional[str] = None):
    qs = ScheduledTask.objects.all().order_by("next_run_at", "-created_at")
    if status:
        qs = qs.filter(status=status)
    return {
        "tasks": [
            {
                "id": str(task.id),
                "prompt": task.prompt,
                "recurrence": task.recurrence,
                "start_at": task.start_at.isoformat() if task.start_at else None,
                "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
                "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
                "status": task.status,
                "is_running": task.is_running,
            }
            for task in qs
        ]
    }


@register_function(
    manifest_id="scheduled_tasks.update_task",
    module="scheduled_tasks",
    name="scheduled_tasks.update_task",
    description="Update a scheduled task (prompt/start/recur/status).",
    params_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "prompt": {"type": "string"},
            "start_at": {"type": "string", "description": "ISO datetime"},
            "recurrence": {"type": "string", "description": "once|daily|weekly|monthly"},
            "status": {"type": "string", "description": "active|paused|completed"},
        },
        "required": ["task_id"],
    },
)
def update_task(
    task_id: str,
    prompt: Optional[str] = None,
    start_at: Optional[str] = None,
    recurrence: Optional[str] = None,
    status: Optional[str] = None,
):
    task = ScheduledTask.objects.get(id=task_id)
    if recurrence and recurrence not in dict(ScheduledTask.RECURRENCE_CHOICES):
        raise ValueError("Invalid recurrence value")
    if status and status not in dict(ScheduledTask.STATUS_CHOICES):
        raise ValueError("Invalid status value")

    if prompt is not None:
        task.prompt = prompt
    if recurrence is not None:
        task.recurrence = recurrence
    if start_at is not None:
        dt = _parse_dt(start_at)
        if not dt:
            raise ValueError("Invalid start_at datetime")
        task.start_at = dt
        if task.status == ScheduledTask.STATUS_ACTIVE:
            task.next_run_at = dt
    if status is not None:
        task.status = status
        if status == ScheduledTask.STATUS_ACTIVE and task.next_run_at is None:
            task.next_run_at = task.start_at
        if status != ScheduledTask.STATUS_ACTIVE:
            task.is_running = False

    task.save(
        update_fields=[
            "prompt",
            "recurrence",
            "start_at",
            "next_run_at",
            "status",
            "is_running",
            "updated_at",
        ]
    )
    return {"id": str(task.id), "status": task.status}


@register_function(
    manifest_id="scheduled_tasks.delete_task",
    module="scheduled_tasks",
    name="scheduled_tasks.delete_task",
    description="Delete a scheduled task and its history.",
    params_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
        },
        "required": ["task_id"],
    },
)
def delete_task(task_id: str):
    task = ScheduledTask.objects.get(id=task_id)
    task.delete()
    return {"deleted": task_id}


@register_function(
    manifest_id="scheduled_tasks.list_runs",
    module="scheduled_tasks",
    name="scheduled_tasks.list_runs",
    description="List recent runs and logs for a scheduled task.",
    params_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["task_id"],
    },
)
def list_runs(task_id: str, limit: int = 10):
    task = ScheduledTask.objects.get(id=task_id)
    runs = ScheduledTaskRun.objects.filter(task=task).order_by("-started_at")[: max(limit or 10, 1)]
    out = []
    for run in runs:
        logs = ScheduledTaskLogEntry.objects.filter(run=run).order_by("created_at")
        out.append(
            {
                "id": str(run.id),
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "summary": run.summary,
                "error_summary": run.error_summary,
                "log_entries": [
                    {
                        "id": str(entry.id),
                        "role": entry.role,
                        "level": entry.level,
                        "message": entry.message,
                        "created_at": entry.created_at.isoformat() if entry.created_at else None,
                    }
                    for entry in logs
                ],
            }
        )
    return {"runs": out}
