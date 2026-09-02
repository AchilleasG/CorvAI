from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import logging
from django.utils import timezone
from django.db import connection
from django.db.models import Q

from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.models import (
    CallSession,
    CallTranscriptEntry,
    PushToken,
    UserMessage,
)
from orchestration.notifications import send_call_push_to_all, send_message_push_to_all
from orchestration.schemas import FunctionCallPayload
from orchestration.services import FunctionRunnerService, ModuleDirectory
from openai_integration.services import ChatAIService

logger = logging.getLogger(__name__)

# Temporarily freeze every automatic end/follow-up planning path. Calls remain
# explicitly controlled by the user while realtime actions continue normally.
AUTOMATIC_CALL_COMPLETION_ENABLED = False
FOLLOW_UP_CALLS_ENABLED = False

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


def is_web_call(session: CallSession) -> bool:
    metadata = session.metadata if isinstance(session.metadata, dict) else {}
    return metadata.get("origin") == "web"


def create_call_session(
    goal: str,
    scheduled_for: Optional[datetime] = None,
    *,
    origin: str = "corv",
) -> CallSession:
    status = CallSession.STATUS_SCHEDULED
    if scheduled_for and scheduled_for <= timezone.now():
        status = CallSession.STATUS_RINGING
    elif not scheduled_for:
        status = CallSession.STATUS_RINGING
    logger.info(
        "call_session create request goal=%s scheduled_for=%s computed_status=%s",
        goal,
        scheduled_for.isoformat() if scheduled_for else None,
        status,
    )
    session = CallSession.objects.create(
        goal=goal,
        status=status,
        scheduled_for=scheduled_for,
        ringing_started_at=timezone.now() if status == CallSession.STATUS_RINGING else None,
        metadata={"origin": origin},
    )
    logger.info("call_session created id=%s status=%s", session.id, session.status)
    if status == CallSession.STATUS_RINGING and not is_web_call(session):
        notify_incoming_call(session)
    return session


def notify_incoming_call(session: CallSession):
    if is_web_call(session):
        logger.info("call_session mobile notification suppressed for web session id=%s", session.id)
        return
    token_count = PushToken.objects.filter(platform="android_fcm").count()
    logger.info(
        "call_session notify_incoming id=%s token_count=%s goal=%s",
        session.id,
        token_count,
        session.goal,
    )
    try:
        send_call_push_to_all(
            title="Incoming call from Corv",
            body=session.goal[:120],
            data={"call_session_id": str(session.id), "type": "call_incoming"},
        )
        logger.info("call_session notify_incoming dispatched id=%s", session.id)
    except Exception:
        logger.exception("call_session notify_incoming failed id=%s", session.id)


def mark_call_missed(session: CallSession):
    logger.info("call_session mark_missed id=%s status=%s", session.id, session.status)
    try:
        existing = UserMessage.objects.filter(
            kind=UserMessage.KIND_CALL_MISSED,
            metadata__call_session_id=str(session.id),
        ).first()
        if existing and session.status == CallSession.STATUS_MISSED:
            return
        session.status = CallSession.STATUS_MISSED
        session.ended_at = timezone.now()
        session.save(update_fields=["status", "ended_at", "updated_at"])
        if is_web_call(session):
            logger.info("call_session missed mobile follow-up suppressed for web session id=%s", session.id)
            return
        title = "Corv"
        draft_body = f"Looks like we missed each other about: {session.goal}"
        phrased_body = ChatAIService.phrase_inbox_message(
            draft_body,
            title=title,
            kind=UserMessage.KIND_CALL_MISSED,
        )
        msg = existing
        if not msg:
            msg = UserMessage.objects.create(
                title=title,
                body=phrased_body,
                kind=UserMessage.KIND_CALL_MISSED,
                metadata={"call_session_id": str(session.id)},
            )
        send_message_push_to_all(
            title=title,
            body=phrased_body,
            data={
                "call_session_id": str(session.id),
                "message_id": str(msg.id) if msg else "",
            },
        )
    except Exception:
        logger.exception("call_session mark_missed failed id=%s", session.id)


def accept_call(session: CallSession):
    logger.info("call_session accept id=%s status=%s", session.id, session.status)
    session.status = CallSession.STATUS_IN_CALL
    session.started_at = timezone.now()
    session.save(update_fields=["status", "started_at", "updated_at"])


def complete_call(session: CallSession):
    logger.info("call_session complete id=%s status=%s", session.id, session.status)
    session.status = CallSession.STATUS_COMPLETED
    session.ended_at = timezone.now()
    session.save(update_fields=["status", "ended_at", "updated_at"])
    summarize_call(session)
    if FOLLOW_UP_CALLS_ENABLED:
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
    call_session: CallSession | None = None,
) -> Dict[str, Any]:
    for attempt in range(2):
        decision = FunctionCallOrchestrator._plan_next_action(
            user_request=user_request,
            tool_catalog=tool_catalog,
            prior_results=prior_results,
            job=None,
            chat_id=None,
            call_session_id=str(call_session.id) if call_session else None,
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
    if not FOLLOW_UP_CALLS_ENABLED:
        logger.info("call follow-up planner frozen session=%s", session.id)
        return []
    transcript = _format_transcript(session)
    user_request = (
        f"Call goal: {session.goal}\n\nTranscript:\n{transcript}\n\n"
        "Decide if follow-up actions are needed. Never repeat actions already recorded as Action result. "
        "You may create scheduled tasks or "
        "schedule a follow-up call session when appropriate. "
        "If the user agreed to do something, schedule a confirmation call about 10 minutes "
        "after the estimated completion time if you can infer it." \
        "If the user can't speak right now send him a text message instead immediately."
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
            coerced = FunctionCallOrchestrator._coerce_result_payload(
                result,
                function_id=call["function_id"],
                params=call.get("params") or {},
            )
            prior_results.append(coerced)
            continue
        if decision.get("done"):
            break


def _active_call_delegation_reply(session: CallSession) -> str:
    """Return an audio-friendly status when this call has active delegated work."""
    from coding.chat_waits import CodingChatWaitService

    state = CodingChatWaitService.list_for_origin(
        call_session=session,
        include_finished=False,
    )
    active = [item for item in state["delegations"] if item["active"]]
    if not active:
        return ""
    waiting = [item for item in active if item["waiting"]]
    selected = waiting or active
    labels = [str(item.get("label") or "delegated task") for item in selected[:3]]
    if len(labels) == 1:
        subject = f'the Codex task called {labels[0]}'
    else:
        subject = f'{len(selected)} Codex tasks, including {", ".join(labels)}'
    if waiting:
        return (
            f"Codex is working on {subject} now. I am waiting for it to finish and will tell you "
            "as soon as it completes. You can interrupt the wait at any time."
        )
    return f"Codex is working on {subject} now. The call can continue while it runs."


def execute_call_action(session: CallSession, instruction: str, max_steps: int = 6) -> str:
    """Run a user-requested Corv action while a realtime call is active."""
    instruction = (instruction or "").strip()
    if not instruction:
        return "I could not run that because the action was empty."
    user_request = (
        f"Call goal: {session.goal}\n\nConversation so far:\n{_format_transcript(session)}\n\n"
        f"Action requested now: {instruction}\n\n"
        "Execute the requested action using the same Corv tools available in text mode. "
        "Return a short plain language account of what happened."
    )
    tool_catalog = ModuleDirectory.function_catalog()
    prior_results: List[Dict[str, Any]] = []
    final_summary = "I could not complete that action."
    for _ in range(max_steps):
        decision = _plan_with_no_clarifications(
            user_request=user_request, tool_catalog=tool_catalog, prior_results=prior_results,
            call_session=session,
        )
        call = decision.get("call")
        if call and call.get("function_id"):
            payload = FunctionCallPayload(
                trace_id=f"realtime-call-{session.id}",
                function_id=call["function_id"], params=call.get("params") or {}, job_id=None,
            )
            result = FunctionRunnerService.run_function_call(payload, job=None, call_session=session)
            coerced = FunctionCallOrchestrator._coerce_result_payload(
                result,
                function_id=call["function_id"],
                params=call.get("params") or {},
            )
            prior_results.append(coerced)
            if payload.function_id in {
                "coding_sessions.delegate_task",
                "coding_sessions.delegate_feature",
            }:
                delegation_reply = _active_call_delegation_reply(session)
                if delegation_reply:
                    final_summary = delegation_reply
                    break
            continue
        if decision.get("done"):
            final_summary = str(decision.get("summary") or decision.get("reply") or "Action completed.")
            if final_summary == "Planner output could not be parsed.":
                final_summary = _active_call_delegation_reply(session) or final_summary
            break
    CallTranscriptEntry.objects.create(
        session=session, role="system", content=f"Action result: {final_summary}"
    )
    return final_summary


def poll_call_sessions(ring_timeout_seconds: int = 45, limit: int = 25) -> int:
    now = timezone.now()
    ran = 0
    db_name = connection.settings_dict.get("NAME")
    scheduled_total = CallSession.objects.filter(status=CallSession.STATUS_SCHEDULED).count()
    next_scheduled = (
        CallSession.objects.filter(status=CallSession.STATUS_SCHEDULED)
        .order_by("scheduled_for")
        .first()
    )
    logger.info(
        "poll_call_sessions start now=%s limit=%s db=%s scheduled_total=%s next_scheduled_id=%s next_scheduled_for=%s",
        now.isoformat(),
        limit,
        db_name,
        scheduled_total,
        next_scheduled.id if next_scheduled else None,
        next_scheduled.scheduled_for.isoformat() if next_scheduled and next_scheduled.scheduled_for else None,
    )
    scheduled = (
        CallSession.objects.filter(status=CallSession.STATUS_SCHEDULED, scheduled_for__lte=now)
        .order_by("scheduled_for")[:limit]
    )
    logger.info("poll_call_sessions due=%s", len(scheduled))
    for session in scheduled:
        logger.info("poll_call_sessions ringing session=%s scheduled_for=%s", session.id, session.scheduled_for)
        session.status = CallSession.STATUS_RINGING
        session.ringing_started_at = now
        session.save(update_fields=["status", "ringing_started_at", "updated_at"])
        notify_incoming_call(session)
        ran += 1

    cutoff = now - timedelta(seconds=ring_timeout_seconds)
    ringing = CallSession.objects.filter(
        Q(metadata__origin__isnull=True) | ~Q(metadata__origin="web"),
        status=CallSession.STATUS_RINGING,
        ringing_started_at__lte=cutoff,
    )[:limit]
    logger.info("poll_call_sessions timeout_candidates=%s cutoff=%s", len(ringing), cutoff.isoformat())
    for session in ringing:
        logger.info("poll_call_sessions mark_missed session=%s", session.id)
        mark_call_missed(session)
        ran += 1
    logger.info("poll_call_sessions end ran=%s", ran)
    return ran
