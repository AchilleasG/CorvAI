from __future__ import annotations

from datetime import datetime
import logging
from typing import Optional

from django.utils import timezone

from orchestration.models import CallSession, UserMessage
from orchestration.registry import register_function
from orchestration.call_processing import create_call_session, accept_call, complete_call, mark_call_missed

logger = logging.getLogger("orchestration.call_processing")


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
    manifest_id="call_sessions.create_session",
    module="call_sessions",
    name="call_sessions.create_session",
    description="Create a call session with a goal; can be immediate or scheduled.",
    params_schema={
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "scheduled_for": {"type": "string", "description": "ISO datetime for scheduled call"},
        },
        "required": ["goal"],
    },
)
def create_session(goal: str, scheduled_for: Optional[str] = None):
    logger.info(
        "call_sessions.create_session invoked goal=%s scheduled_for=%s",
        goal,
        scheduled_for,
    )
    dt = _parse_dt(scheduled_for)
    logger.info(
        "call_sessions.create_session parsed scheduled_for=%s",
        dt.isoformat() if dt else None,
    )
    session = create_call_session(goal=goal, scheduled_for=dt)
    logger.info(
        "call_sessions.create_session created id=%s status=%s",
        session.id,
        session.status,
    )
    return {"id": str(session.id), "status": session.status}


@register_function(
    manifest_id="call_sessions.list_sessions",
    module="call_sessions",
    name="call_sessions.list_sessions",
    description="List call sessions with optional status filter.",
    params_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "scheduled|ringing|in_call|missed|completed|canceled"},
        },
    },
)
def list_sessions(status: Optional[str] = None):
    qs = CallSession.objects.all().order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    return {
        "sessions": [
            {
                "id": str(s.id),
                "goal": s.goal,
                "status": s.status,
                "scheduled_for": s.scheduled_for.isoformat() if s.scheduled_for else None,
                "summary": s.summary,
            }
            for s in qs[:50]
        ]
    }


@register_function(
    manifest_id="call_sessions.update_session",
    module="call_sessions",
    name="call_sessions.update_session",
    description="Update a call session status.",
    params_schema={
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "status": {"type": "string", "description": "scheduled|ringing|in_call|missed|completed|canceled"},
        },
        "required": ["session_id", "status"],
    },
)
def update_session(session_id: str, status: str):
    session = CallSession.objects.get(id=session_id)
    if status == CallSession.STATUS_IN_CALL:
        accept_call(session)
    elif status == CallSession.STATUS_COMPLETED:
        complete_call(session)
    elif status == CallSession.STATUS_MISSED:
        mark_call_missed(session)
    else:
        session.status = status
        session.save(update_fields=["status", "updated_at"])
    return {"id": str(session.id), "status": session.status}


@register_function(
    manifest_id="call_sessions.send_message",
    module="call_sessions",
    name="call_sessions.send_message",
    description="Send a standalone user message to the inbox.",
    params_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "kind": {"type": "string", "description": "info|call_missed|call_text"},
        },
        "required": ["body"],
    },
)
def send_message(title: str = "", body: str = "", kind: str = "info"):
    msg = UserMessage.objects.create(title=title, body=body, kind=kind)
    return {"id": str(msg.id)}
