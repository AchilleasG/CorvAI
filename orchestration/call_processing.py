from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import logging
from django.utils import timezone

from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.models import (
    CallSession,
    UserMessage,
)
from orchestration.notifications import send_call_push_to_all, send_push_to_all
from orchestration.schemas import FunctionCallPayload
from orchestration.services import FunctionRunnerService, ModuleDirectory
from openai_integration.services import ChatAIService

logger = logging.getLogger(__name__)

NO_CLARIFICATION_NOTE = (
    "No user clarifications are available. Do not ask the user; make reasonable "
    "assumptions and complete the task to the best of your ability."
)


def _format_transcript(session: CallSession) -> str:
    lines = []
    for entry in session.transcript_entries.all().order_by("created_at"):
        ts = entry.created_at.isoformat() if entry.created_at else ""
        lines.append(f"{entry.role}: {ts} {entry.content}")
    return "\n".join(lines)


def create_call_session(goal: str, scheduled_for: Optional[datetime] = None) -> CallSession:
    status = CallSession.STATUS_SCHEDULED
    if scheduled_for and scheduled_for <= timezone.now():
        status = CallSession.STATUS_RINGING
    elif not scheduled_for:
        status = CallSession.STATUS_RINGING
    session = CallSession.objects.create(
        goal=goal,
        status=status,
        scheduled_for=scheduled_for,
        ringing_started_at=timezone.now() if status == CallSession.STATUS_RINGING else None,
    )
    if status == CallSession.STATUS_RINGING:
        notify_incoming_call(session)
    return session


def notify_incoming_call(session: CallSession):
    send_call_push_to_all(
        title="Incoming call from Corv",
        body=session.goal[:120],
        data={"call_session_id": str(session.id), "type": "call_incoming"},
    )


def mark_call_missed(session: CallSession):
    session.status = CallSession.STATUS_MISSED
    session.ended_at = timezone.now()
    session.save(update_fields=["status", "ended_at", "updated_at"])
    UserMessage.objects.create(
        title="Corv text",
        body=f"Missed call: {session.goal}",
        kind=UserMessage.KIND_CALL_TEXT,
        metadata={"call_session_id": str(session.id)},
    )
    send_push_to_all(
        title="Missed call from Corv",
        body=session.goal[:120],
        data={"call_session_id": str(session.id), "type": "call_missed"},
    )


def accept_call(session: CallSession):
    session.status = CallSession.STATUS_IN_CALL
    session.started_at = timezone.now()
    session.save(update_fields=["status", "started_at", "updated_at"])


def complete_call(session: CallSession):
    session.status = CallSession.STATUS_COMPLETED
    session.ended_at = timezone.now()
    session.save(update_fields=["status", "ended_at", "updated_at"])
    summarize_call(session)
    process_call_actions(session)


def summarize_call(session: CallSession):
    transcript = _format_transcript(session)
    context = f"Goal: {session.goal}\n\nTranscript:\n{transcript}"
    summary = ChatAIService.summarize_call(context)
    session.summary = summary
    session.save(update_fields=["summary", "updated_at"])


def should_end_call(session: CallSession, max_entries: int = 12) -> bool:
    entries = list(session.transcript_entries.all().order_by("-created_at")[:max_entries])
    if not entries:
        return False
    entries = list(reversed(entries))
    lines = []
    for entry in entries:
        lines.append(f"{entry.role}: {entry.content}")
    context = f"Goal: {session.goal}\n\nTranscript:\n" + "\n".join(lines)
    decision = ChatAIService.should_end_call(context, model="gpt-5-mini")
    logger.info(
        "call_monitor decision=%s session=%s transcript=%s",
        decision,
        session.id,
        "\\n".join(lines),
    )
    return decision


def _plan_with_no_clarifications(
    *,
    user_request: str,
    tool_catalog: List[Dict[str, Any]],
    prior_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    for attempt in range(2):
        decision = FunctionCallOrchestrator._plan_next_action(
            user_request=user_request,
            tool_catalog=tool_catalog,
            prior_results=prior_results,
            job=None,
            chat_id=None,
        )
        if not decision.get("ask_user"):
            return decision
        if attempt == 0:
            user_request = (
                f"{user_request}\n\nSystem: {NO_CLARIFICATION_NOTE} "
                "If details are missing, choose sensible defaults and proceed."
            )
    return {"done": True, "summary": "Planner requested user input; completed with best-effort assumptions."}


def process_call_actions(session: CallSession, max_steps: int = 6):
    transcript = _format_transcript(session)
    user_request = (
        f"Call goal: {session.goal}\n\nTranscript:\n{transcript}\n\n"
        "Decide if follow-up actions are needed. You may create scheduled tasks or "
        "schedule a follow-up call session when appropriate. "
        "If the user agreed to do something, schedule a confirmation call about 10 minutes "
        "after the estimated completion time if you can infer it."
    )
    tool_catalog = ModuleDirectory.function_catalog()
    prior_results: List[Dict[str, Any]] = []

    for step in range(max_steps):
        decision = _plan_with_no_clarifications(
            user_request=user_request,
            tool_catalog=tool_catalog,
            prior_results=prior_results,
        )
        call = decision.get("call")
        if call and call.get("function_id"):
            payload = FunctionCallPayload(
                trace_id="call-post",
                function_id=call["function_id"],
                params=call.get("params") or {},
                job_id=None,
            )
            result = FunctionRunnerService.run_function_call(payload, job=None)
            coerced = FunctionCallOrchestrator._coerce_result_payload(result)
            coerced["function_id"] = call["function_id"]
            coerced["params"] = call.get("params") or {}
            prior_results.append(coerced)
            continue
        if decision.get("done"):
            break


def poll_call_sessions(ring_timeout_seconds: int = 45, limit: int = 25) -> int:
    now = timezone.now()
    ran = 0
    scheduled = (
        CallSession.objects.filter(status=CallSession.STATUS_SCHEDULED, scheduled_for__lte=now)
        .order_by("scheduled_for")[:limit]
    )
    for session in scheduled:
        session.status = CallSession.STATUS_RINGING
        session.ringing_started_at = now
        session.save(update_fields=["status", "ringing_started_at", "updated_at"])
        notify_incoming_call(session)
        ran += 1

    cutoff = now - timedelta(seconds=ring_timeout_seconds)
    ringing = CallSession.objects.filter(
        status=CallSession.STATUS_RINGING, ringing_started_at__lte=cutoff
    )[:limit]
    for session in ringing:
        mark_call_missed(session)
        ran += 1
    return ran
