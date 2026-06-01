from __future__ import annotations

from datetime import datetime
from typing import Optional

from django.utils import timezone

from orchestration.models import Objective, ObjectiveLog, ObjectiveTask
from orchestration.registry import register_function


def _parse_dt(value: Optional[str]):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone=timezone.utc)
    return dt


def _task_payload(task: ObjectiveTask) -> dict:
    return {
        "id": str(task.id),
        "objective_id": str(task.objective_id),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "estimated_effort_minutes": task.estimated_effort_minutes,
        "remaining_effort_minutes": task.remaining_effort_minutes,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "sort_order": task.sort_order,
        "metadata": task.metadata or {},
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _log_payload(log: ObjectiveLog) -> dict:
    return {
        "id": str(log.id),
        "objective_id": str(log.objective_id),
        "task_id": str(log.task_id) if log.task_id else None,
        "kind": log.kind,
        "text": log.text,
        "minutes_spent": log.minutes_spent,
        "logged_at": log.logged_at.isoformat() if log.logged_at else None,
        "metadata": log.metadata or {},
    }


def _objective_payload(objective: Objective) -> dict:
    return {
        "id": str(objective.id),
        "parent_id": str(objective.parent_id) if objective.parent_id else None,
        "title": objective.title,
        "description": objective.description,
        "status": objective.status,
        "deadline_at": objective.deadline_at.isoformat() if objective.deadline_at else None,
        "estimated_effort_minutes": objective.estimated_effort_minutes,
        "remaining_effort_minutes": objective.remaining_effort_minutes,
        "priority": objective.priority,
        "notes": objective.notes,
        "metadata": objective.metadata or {},
    }


@register_function(
    manifest_id="objectives.list_objectives",
    module="objectives",
    name="objectives.list_objectives",
    description="List objectives. With parent_id, list that objective's children. Without parent_id, status='all' returns all objectives; otherwise root objectives are returned.",
    params_schema={
        "type": "object",
        "properties": {
            "parent_id": {"type": "string"},
            "status": {"type": "string"},
        },
    },
)
def list_objectives(parent_id: Optional[str] = None, status: Optional[str] = None):
    qs = Objective.objects.all().order_by("deadline_at", "-priority", "created_at")
    normalized_status = str(status or "").strip().lower()
    if parent_id:
        qs = qs.filter(parent_id=parent_id)
    elif normalized_status != "all":
        qs = qs.filter(parent__isnull=True)
    if normalized_status and normalized_status != "all":
        qs = qs.filter(status=status)
    return {"objectives": [_objective_payload(objective) for objective in qs]}


@register_function(
    manifest_id="objectives.get_objective",
    module="objectives",
    name="objectives.get_objective",
    description="Get one objective with its tasks and recent logs.",
    params_schema={
        "type": "object",
        "properties": {"objective_id": {"type": "string"}},
        "required": ["objective_id"],
    },
)
def get_objective(objective_id: str):
    objective = Objective.objects.get(id=objective_id)
    return {
        **_objective_payload(objective),
        "tasks": [_task_payload(task) for task in objective.tasks.all().order_by("sort_order", "created_at")],
        "logs": [_log_payload(log) for log in objective.logs.all().order_by("-logged_at", "-created_at")[:20]],
    }


@register_function(
    manifest_id="objectives.create_objective",
    module="objectives",
    name="objectives.create_objective",
    description="Create a new objective.",
    params_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "parent_id": {"type": "string"},
            "description": {"type": "string"},
            "deadline_at": {"type": "string"},
            "estimated_effort_minutes": {"type": "integer"},
            "remaining_effort_minutes": {"type": "integer"},
            "priority": {"type": "integer"},
            "notes": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["title"],
    },
)
def create_objective(
    title: str,
    parent_id: Optional[str] = None,
    description: str = "",
    deadline_at: Optional[str] = None,
    estimated_effort_minutes: Optional[int] = None,
    remaining_effort_minutes: Optional[int] = None,
    priority: int = 0,
    notes: str = "",
    metadata: Optional[dict] = None,
):
    parent = Objective.objects.filter(id=parent_id).first() if parent_id else None
    objective = Objective.objects.create(
        parent=parent,
        title=title,
        description=description,
        deadline_at=_parse_dt(deadline_at) if deadline_at else None,
        estimated_effort_minutes=estimated_effort_minutes,
        remaining_effort_minutes=remaining_effort_minutes,
        priority=priority or 0,
        notes=notes,
        metadata=metadata or {},
        chat=parent.chat if parent else None,
    )
    return _objective_payload(objective)


@register_function(
    manifest_id="objectives.update_objective",
    module="objectives",
    name="objectives.update_objective",
    description="Update an objective.",
    params_schema={
        "type": "object",
        "properties": {
            "objective_id": {"type": "string"},
            "parent_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string"},
            "deadline_at": {"type": "string"},
            "estimated_effort_minutes": {"type": "integer"},
            "remaining_effort_minutes": {"type": "integer"},
            "priority": {"type": "integer"},
            "notes": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["objective_id"],
    },
)
def update_objective(objective_id: str, **kwargs):
    objective = Objective.objects.get(id=objective_id)
    parent_id = kwargs.pop("parent_id", None)
    if parent_id is not None:
        objective.parent = Objective.objects.filter(id=parent_id).first() if parent_id else None
    for key in ["title", "description", "status", "notes"]:
        if key in kwargs and kwargs[key] is not None:
            setattr(objective, key, kwargs[key])
    for key in ["estimated_effort_minutes", "remaining_effort_minutes", "priority"]:
        if key in kwargs and kwargs[key] is not None:
            setattr(objective, key, int(kwargs[key]))
    if "deadline_at" in kwargs:
        objective.deadline_at = _parse_dt(kwargs["deadline_at"]) if kwargs["deadline_at"] else None
    if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
        objective.metadata = kwargs["metadata"]
    objective.save()
    return _objective_payload(objective)


@register_function(
    manifest_id="objectives.delete_objective",
    module="objectives",
    name="objectives.delete_objective",
    description="Delete an objective.",
    params_schema={
        "type": "object",
        "properties": {"objective_id": {"type": "string"}},
        "required": ["objective_id"],
    },
)
def delete_objective(objective_id: str):
    deleted, _ = Objective.objects.filter(id=objective_id).delete()
    return {"deleted": bool(deleted)}


@register_function(
    manifest_id="objectives.create_task",
    module="objectives",
    name="objectives.create_task",
    description="Create a task under an objective.",
    params_schema={
        "type": "object",
        "properties": {
            "objective_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string"},
            "estimated_effort_minutes": {"type": "integer"},
            "remaining_effort_minutes": {"type": "integer"},
            "due_at": {"type": "string"},
            "sort_order": {"type": "integer"},
            "metadata": {"type": "object"},
        },
        "required": ["objective_id", "title"],
    },
)
def create_task(
    objective_id: str,
    title: str,
    description: str = "",
    status: str = ObjectiveTask.STATUS_TODO,
    estimated_effort_minutes: Optional[int] = None,
    remaining_effort_minutes: Optional[int] = None,
    due_at: Optional[str] = None,
    sort_order: int = 0,
    metadata: Optional[dict] = None,
):
    task = ObjectiveTask.objects.create(
        objective_id=objective_id,
        title=title,
        description=description,
        status=status,
        estimated_effort_minutes=estimated_effort_minutes,
        remaining_effort_minutes=remaining_effort_minutes,
        due_at=_parse_dt(due_at) if due_at else None,
        sort_order=sort_order or 0,
        metadata=metadata or {},
    )
    return _task_payload(task)


@register_function(
    manifest_id="objectives.update_task",
    module="objectives",
    name="objectives.update_task",
    description="Update an objective task.",
    params_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string"},
            "estimated_effort_minutes": {"type": "integer"},
            "remaining_effort_minutes": {"type": "integer"},
            "due_at": {"type": "string"},
            "sort_order": {"type": "integer"},
            "metadata": {"type": "object"},
        },
        "required": ["task_id"],
    },
)
def update_task(task_id: str, **kwargs):
    task = ObjectiveTask.objects.get(id=task_id)
    for key in ["title", "description", "status"]:
        if key in kwargs and kwargs[key] is not None:
            setattr(task, key, kwargs[key])
    for key in ["estimated_effort_minutes", "remaining_effort_minutes", "sort_order"]:
        if key in kwargs and kwargs[key] is not None:
            setattr(task, key, int(kwargs[key]))
    if "due_at" in kwargs:
        task.due_at = _parse_dt(kwargs["due_at"]) if kwargs["due_at"] else None
    if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
        task.metadata = kwargs["metadata"]
    if "status" in kwargs:
        task.completed_at = timezone.now() if task.status == ObjectiveTask.STATUS_DONE else None
    task.save()
    return _task_payload(task)


@register_function(
    manifest_id="objectives.delete_task",
    module="objectives",
    name="objectives.delete_task",
    description="Delete an objective task.",
    params_schema={
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    },
)
def delete_task(task_id: str):
    deleted, _ = ObjectiveTask.objects.filter(id=task_id).delete()
    return {"deleted": bool(deleted)}


@register_function(
    manifest_id="objectives.list_logs",
    module="objectives",
    name="objectives.list_logs",
    description="List logs for an objective.",
    params_schema={
        "type": "object",
        "properties": {"objective_id": {"type": "string"}},
        "required": ["objective_id"],
    },
)
def list_logs(objective_id: str):
    logs = ObjectiveLog.objects.filter(objective_id=objective_id).order_by("-logged_at", "-created_at")
    return {"logs": [_log_payload(log) for log in logs]}


@register_function(
    manifest_id="objectives.create_log",
    module="objectives",
    name="objectives.create_log",
    description="Create a log entry for an objective or task.",
    params_schema={
        "type": "object",
        "properties": {
            "objective_id": {"type": "string"},
            "task_id": {"type": "string"},
            "kind": {"type": "string"},
            "text": {"type": "string"},
            "minutes_spent": {"type": "integer"},
            "logged_at": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["objective_id"],
    },
)
def create_log(
    objective_id: str,
    task_id: Optional[str] = None,
    kind: str = ObjectiveLog.KIND_NOTE,
    text: str = "",
    minutes_spent: Optional[int] = None,
    logged_at: Optional[str] = None,
    metadata: Optional[dict] = None,
):
    log = ObjectiveLog.objects.create(
        objective_id=objective_id,
        task_id=task_id,
        kind=kind,
        text=text,
        minutes_spent=minutes_spent,
        logged_at=_parse_dt(logged_at) if logged_at else timezone.now(),
        metadata=metadata or {},
    )
    return _log_payload(log)


@register_function(
    manifest_id="objectives.update_log",
    module="objectives",
    name="objectives.update_log",
    description="Update an objective log entry.",
    params_schema={
        "type": "object",
        "properties": {
            "log_id": {"type": "string"},
            "task_id": {"type": "string"},
            "kind": {"type": "string"},
            "text": {"type": "string"},
            "minutes_spent": {"type": "integer"},
            "logged_at": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["log_id"],
    },
)
def update_log(log_id: str, **kwargs):
    log = ObjectiveLog.objects.get(id=log_id)
    for key in ["kind", "text"]:
        if key in kwargs and kwargs[key] is not None:
            setattr(log, key, kwargs[key])
    if "task_id" in kwargs:
        log.task_id = kwargs["task_id"] or None
    if "minutes_spent" in kwargs:
        log.minutes_spent = int(kwargs["minutes_spent"]) if kwargs["minutes_spent"] is not None else None
    if "logged_at" in kwargs:
        log.logged_at = _parse_dt(kwargs["logged_at"]) if kwargs["logged_at"] else timezone.now()
    if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
        log.metadata = kwargs["metadata"]
    log.save()
    return _log_payload(log)


@register_function(
    manifest_id="objectives.delete_log",
    module="objectives",
    name="objectives.delete_log",
    description="Delete an objective log entry.",
    params_schema={
        "type": "object",
        "properties": {"log_id": {"type": "string"}},
        "required": ["log_id"],
    },
)
def delete_log(log_id: str):
    deleted, _ = ObjectiveLog.objects.filter(id=log_id).delete()
    return {"deleted": bool(deleted)}
