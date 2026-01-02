import os
from typing import Any, Dict, List, Optional

import httpx

from orchestration.registry import register_function

DEFAULT_BASE_URL = os.getenv("TIMELOGGER_BASE_URL", "").rstrip("/")


class TimeLoggerError(Exception):
    pass


def _client(base_url: Optional[str] = None, token: Optional[str] = None) -> httpx.Client:
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
    if not base_url:
        raise TimeLoggerError("base_url is required (or set TIMELOGGER_BASE_URL)")
    headers = {}
    if token:
        headers["Authorization"] = f"Token {token}"
    # DRF typically expects trailing slashes; normalize to avoid double slashes.
    return httpx.Client(base_url=f"{base_url}/api/v1", headers=headers, timeout=20.0)


def _handle(resp: httpx.Response) -> Any:
    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            data = resp.text
        raise TimeLoggerError(f"{resp.status_code}: {data}")
    if resp.status_code == 204:
        return None
    return resp.json()


@register_function(
    manifest_id="time_logger.list_projects",
    module="time_logger",
    description="List projects.",
    params_schema={
        "type": "object",
        "properties": {
            "base_url": {"type": "string", "description": "API base (e.g., https://timelogger)"},
            "token": {"type": "string", "description": "Auth token"},
            "include_archived": {"type": "boolean", "default": False},
            "start": {"type": "string", "description": "ISO datetime for month window start"},
            "end": {"type": "string", "description": "ISO datetime for month window end"},
        },
    },
)
def list_projects(
    token: str,
    base_url: Optional[str] = None,
    include_archived: bool = False,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    with _client(base_url, token) as client:
        params: Dict[str, Any] = {"include_archived": include_archived}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        resp = client.get("/projects/", params=params)
        return _handle(resp)


@register_function(
    manifest_id="time_logger.list_tasks",
    module="time_logger",
    description="List tasks, optionally filtered by project.",
    params_schema={
        "type": "object",
        "properties": {
            "token": {"type": "string"},
            "base_url": {"type": "string"},
            "project_id": {"type": "integer"},
            "include_archived": {"type": "boolean", "default": False},
        },
        "required": ["token"],
    },
)
def list_tasks(
    token: str,
    base_url: Optional[str] = None,
    project_id: Optional[int] = None,
    include_archived: bool = False,
):
    with _client(base_url, token) as client:
        params: Dict[str, Any] = {"include_archived": include_archived}
        if project_id is not None:
            params["project"] = project_id
        resp = client.get("/tasks/", params=params)
        return _handle(resp)


@register_function(
    manifest_id="time_logger.list_time_entries",
    module="time_logger",
    description="List time entries with optional filters.",
    params_schema={
        "type": "object",
        "properties": {
            "token": {"type": "string"},
            "base_url": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "project": {"type": "integer"},
            "task": {"type": "integer"},
            "search": {"type": "string"},
            "page": {"type": "integer"},
        },
        "required": ["token"],
    },
)
def list_time_entries(
    token: str,
    base_url: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    project: Optional[int] = None,
    task: Optional[int] = None,
    search: Optional[str] = None,
    page: Optional[int] = None,
):
    with _client(base_url, token) as client:
        params: Dict[str, Any] = {}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if project is not None:
            params["project"] = project
        if task is not None:
            params["task"] = task
        if search:
            params["search"] = search
        if page:
            params["page"] = page
        resp = client.get("/time-entries/", params=params)
        return _handle(resp)


@register_function(
    manifest_id="time_logger.timer_get",
    module="time_logger",
    description="Get current timer status.",
    params_schema={
        "type": "object",
        "properties": {"token": {"type": "string"}, "base_url": {"type": "string"}},
        "required": ["token"],
    },
)
def timer_get(token: str, base_url: Optional[str] = None):
    with _client(base_url, token) as client:
        resp = client.get("/timer/")
        return _handle(resp)


@register_function(
    manifest_id="time_logger.timer_start",
    module="time_logger",
    description="Start the timer for a project/task.",
    params_schema={
        "type": "object",
        "properties": {
            "token": {"type": "string"},
            "base_url": {"type": "string"},
            "project_id": {"type": "integer"},
            "task_id": {"type": "integer"},
            "started_at": {"type": "string", "description": "Optional ISO datetime"},
        },
        "required": ["token", "project_id", "task_id"],
    },
)
def timer_start(token: str, project_id: int, task_id: int, base_url: Optional[str] = None, started_at: Optional[str] = None):
    with _client(base_url, token) as client:
        payload: Dict[str, Any] = {"project_id": project_id, "task_id": task_id}
        if started_at:
            payload["started_at"] = started_at
        resp = client.post("/timer/start/", json=payload)
        return _handle(resp)


@register_function(
    manifest_id="time_logger.timer_pause",
    module="time_logger",
    description="Pause the current timer.",
    params_schema={
        "type": "object",
        "properties": {"token": {"type": "string"}, "base_url": {"type": "string"}},
        "required": ["token"],
    },
)
def timer_pause(token: str, base_url: Optional[str] = None):
    with _client(base_url, token) as client:
        resp = client.post("/timer/pause/")
        return _handle(resp)


@register_function(
    manifest_id="time_logger.timer_resume",
    module="time_logger",
    description="Resume a paused timer.",
    params_schema={
        "type": "object",
        "properties": {"token": {"type": "string"}, "base_url": {"type": "string"}},
        "required": ["token"],
    },
)
def timer_resume(token: str, base_url: Optional[str] = None):
    with _client(base_url, token) as client:
        resp = client.post("/timer/resume/")
        return _handle(resp)


@register_function(
    manifest_id="time_logger.timer_stop",
    module="time_logger",
    description="Stop the timer and create an entry.",
    params_schema={
        "type": "object",
        "properties": {
            "token": {"type": "string"},
            "base_url": {"type": "string"},
            "notes": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["token"],
    },
)
def timer_stop(token: str, base_url: Optional[str] = None, notes: Optional[str] = None, tags: Optional[List[str]] = None):
    with _client(base_url, token) as client:
        payload: Dict[str, Any] = {}
        if notes:
            payload["notes"] = notes
        if tags:
            payload["tags"] = tags
        resp = client.post("/timer/stop/", json=payload)
        return _handle(resp)


@register_function(
    manifest_id="time_logger.timer_cancel",
    module="time_logger",
    description="Cancel the current timer (reset to idle).",
    params_schema={
        "type": "object",
        "properties": {"token": {"type": "string"}, "base_url": {"type": "string"}},
        "required": ["token"],
    },
)
def timer_cancel(token: str, base_url: Optional[str] = None):
    with _client(base_url, token) as client:
        resp = client.post("/timer/cancel/")
        return _handle(resp)


@register_function(
    manifest_id="time_logger.create_time_entry",
    module="time_logger",
    description="Create a manual time entry.",
    params_schema={
        "type": "object",
        "properties": {
            "token": {"type": "string"},
            "base_url": {"type": "string"},
            "project_id": {"type": "integer"},
            "task_id": {"type": "integer"},
            "start_at": {"type": "string"},
            "end_at": {"type": "string"},
            "notes": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["token", "project_id", "task_id", "start_at", "end_at"],
    },
)
def create_time_entry(
    token: str,
    project_id: int,
    task_id: int,
    start_at: str,
    end_at: str,
    base_url: Optional[str] = None,
    notes: Optional[str] = None,
    tags: Optional[List[str]] = None,
):
    with _client(base_url, token) as client:
        payload: Dict[str, Any] = {
            "project_id": project_id,
            "task_id": task_id,
            "start_at": start_at,
            "end_at": end_at,
        }
        if notes:
            payload["notes"] = notes
        if tags:
            payload["tags"] = tags
        resp = client.post("/time-entries/", json=payload)
        return _handle(resp)
