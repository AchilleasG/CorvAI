import time
from uuid import UUID

from django.db import close_old_connections
from django.db.models import Q

from coding.delegations import FeatureDelegationService
from coding.models import CodingSession, CodingTurn, FeatureDelegation
from coding.services import CodingSessionService
from orchestration.registry import register_function
from ssh_connections.models import SshMachine


def _session(value: str) -> CodingSession:
    value = (value or "").strip()
    if not value:
        raise ValueError("Coding session name or id is required")
    query = Q(name__iexact=value)
    try:
        query |= Q(pk=UUID(value))
    except (TypeError, ValueError):
        pass
    matches = list(CodingSession.objects.select_related("machine").filter(query)[:2])
    if not matches:
        raise ValueError(f"Coding session '{value}' was not found")
    if len(matches) > 1:
        raise ValueError(f"Coding session '{value}' is ambiguous; use its id")
    return matches[0]


def _machine(value: str = "") -> SshMachine:
    value = (value or "").strip()
    if not value:
        default = SshMachine.objects.filter(is_default=True, allow_ai_commands=True).first()
        if default:
            return default
        raise ValueError("SSH machine name or id is required because no default is configured")
    query = Q(name__iexact=value)
    try:
        query |= Q(pk=UUID(value))
    except (TypeError, ValueError):
        pass
    matches = list(SshMachine.objects.filter(query)[:2])
    if not matches:
        raise ValueError(f"SSH machine '{value}' was not found")
    if len(matches) > 1:
        raise ValueError(f"SSH machine '{value}' is ambiguous")
    return matches[0]


def _delegation(value: str) -> FeatureDelegation:
    value = (value or "").strip()
    if not value:
        raise ValueError("Feature delegation title or id is required")
    query = Q(title__iexact=value)
    try:
        query |= Q(pk=UUID(value))
    except (TypeError, ValueError):
        pass
    matches = list(FeatureDelegation.objects.select_related("session__machine").filter(query)[:2])
    if not matches:
        raise ValueError(f"Feature delegation '{value}' was not found")
    if len(matches) > 1:
        raise ValueError(f"Feature delegation '{value}' is ambiguous; use its id")
    return matches[0]


def _wait_for_turn(target: CodingSession, turn: CodingTurn, wait_seconds: int) -> dict:
    deadline = time.monotonic() + max(0, min(int(wait_seconds), 900))
    while time.monotonic() < deadline:
        close_old_connections()
        turn.refresh_from_db()
        if turn.status not in (CodingTurn.STATUS_QUEUED, CodingTurn.STATUS_RUNNING):
            target.refresh_from_db()
            return CodingSessionService.session_payload(target)
        time.sleep(0.5)
    target.refresh_from_db()
    payload = CodingSessionService.session_payload(target)
    payload["message"] = "Codex is still working; check this session again for its result."
    return payload


@register_function(
    manifest_id="coding_sessions.list_sessions",
    module="coding_sessions",
    description="List persistent Codex coding sessions, their machines, and current state.",
    params_schema={"type": "object", "properties": {}},
)
def list_sessions():
    return {
        "sessions": [
            CodingSessionService.session_payload(session, include_turns=False)
            for session in CodingSession.objects.select_related("machine").all()
        ]
    }


@register_function(
    manifest_id="coding_sessions.get_activity",
    module="coding_sessions",
    description="Show currently running coding sessions and feature delegations with bounded recent coder and QA logs.",
    params_schema={
        "type": "object",
        "properties": {
            "include_inactive": {"type": "boolean", "default": False},
            "recent_log_chars": {"type": "integer", "minimum": 500, "maximum": 20000, "default": 6000},
        },
    },
)
def get_activity(include_inactive: bool = False, recent_log_chars: int = 6000):
    """Return an at-a-glance coding status suitable for Corv and voice calls."""
    active_session_statuses = [
        CodingSession.STATUS_RUNNING,
        CodingSession.STATUS_NEEDS_INPUT,
        CodingSession.STATUS_DIRECT,
    ]
    active_delegation_statuses = [
        FeatureDelegation.STATUS_QUEUED,
        FeatureDelegation.STATUS_CODING,
        FeatureDelegation.STATUS_QA,
        FeatureDelegation.STATUS_FIXING,
        FeatureDelegation.STATUS_NEEDS_INPUT,
    ]
    sessions = CodingSession.objects.select_related("machine").all()
    delegations = FeatureDelegation.objects.select_related("session__machine").all()
    if not include_inactive:
        sessions = sessions.filter(status__in=active_session_statuses)
        delegations = delegations.filter(status__in=active_delegation_statuses)
    limit = max(500, min(int(recent_log_chars), 20000))
    session_items = []
    for session in sessions[:50]:
        latest_turn = session.turns.first()
        payload = {
            "id": str(session.pk),
            "name": session.name,
            "machine_name": session.machine.name,
            "remote_working_directory": session.remote_working_directory,
            "status": session.status,
            "last_summary": session.last_summary,
            "pending_question": session.pending_question,
            "pending_options": session.pending_options,
            "last_error": session.last_error,
            "updated_at": session.updated_at.isoformat(),
            "latest_turn": CodingSessionService.turn_payload(latest_turn) if latest_turn else None,
        }
        logs = CodingSessionService.live_logs_payload(session)
        payload["recent_logs"] = (logs.get("content") or "")[-limit:]
        session_items.append(payload)
    delegation_items = []
    for item in delegations[:50]:
        latest_qa = item.qa_runs.first()
        delegation_items.append({
            "id": str(item.pk),
            "session_id": str(item.session_id),
            "session_name": item.session.name,
            "machine_name": item.session.machine.name,
            "title": item.title,
            "status": item.status,
            "current_iteration": item.current_iteration,
            "max_iterations": item.max_iterations,
            "implementation_summary": item.implementation_summary,
            "qa_summary": item.qa_summary,
            "pending_question": item.pending_question,
            "pending_options": item.pending_options,
            "last_error": item.last_error,
            "updated_at": item.updated_at.isoformat(),
            "latest_qa": {
                "status": latest_qa.status,
                "iteration": latest_qa.iteration,
                "summary": latest_qa.summary,
                "failures": latest_qa.failures,
                "recent_logs": (latest_qa.event_log or "")[-limit:],
            } if latest_qa else None,
        })
    return {
        "has_running_work": bool(session_items or delegation_items),
        "active_session_count": len(session_items),
        "active_delegation_count": len(delegation_items),
        "sessions": session_items,
        "delegations": delegation_items,
    }


@register_function(
    manifest_id="coding_sessions.create_session",
    module="coding_sessions",
    description="Create a persistent full-access Codex session. Omit machine to use the user's default SSH machine.",
    params_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "machine": {"type": "string", "description": "Saved SSH machine name/id; omit to use the default"},
            "remote_working_directory": {"type": "string"},
        },
        "required": ["name", "remote_working_directory"],
    },
)
def create_session(name: str, machine: str = "", remote_working_directory: str = "~"):
    target = _machine(machine)
    if not target.allow_ai_commands:
        raise PermissionError(f"Corv command access is disabled for machine '{target.name}'")
    session = CodingSession.objects.create(
        name=name.strip(),
        machine=target,
        remote_working_directory=(remote_working_directory or "~").strip(),
    )
    try:
        CodingSessionService.prepare_workspace(session)
    except Exception:
        session.delete()
        raise
    return CodingSessionService.session_payload(session)


@register_function(
    manifest_id="coding_sessions.delegate_task",
    module="coding_sessions",
    description="Send a specific instruction to an existing persistent Codex session for a small one-turn task. The saved Codex thread, repository context, and working directory are retained. Use get_session to check completion or a pending decision.",
    params_schema={
        "type": "object",
        "properties": {
            "session": {"type": "string", "description": "Coding session display name or UUID; names returned by list_sessions are accepted directly"},
            "task": {"type": "string", "description": "The exact task or command-like instruction for Codex to carry out in this session"},
            "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 900, "default": 0},
            "wait_for_completion": {"type": "boolean", "default": True, "description": "Defaults to true so Corv reports back; set false only when the user asks not to wait"},
        },
        "required": ["session", "task"],
    },
)
def delegate_task(session: str, task: str, wait_seconds: int = 0, wait_for_completion: bool = True):
    target = _session(session)
    turn = CodingSessionService.start_turn(target, task, source=CodingTurn.SOURCE_CORV)
    payload = _wait_for_turn(target, turn, wait_seconds)
    payload["delegated_turn_id"] = str(turn.pk)
    payload["wait_for_completion"] = bool(wait_for_completion)
    return payload


@register_function(
    manifest_id="coding_sessions.get_session",
    module="coding_sessions",
    description="Get a Codex coding session's task results, errors, or pending decision.",
    params_schema={
        "type": "object",
        "properties": {"session": {"type": "string", "description": "Coding session display name or UUID"}},
        "required": ["session"],
    },
)
def get_session(session: str):
    return CodingSessionService.session_payload(_session(session))


@register_function(
    manifest_id="coding_sessions.answer_decision",
    module="coding_sessions",
    description="Give Codex the user's answer when a coding session is waiting for a decision.",
    params_schema={
        "type": "object",
        "properties": {
            "session": {"type": "string", "description": "Coding session display name or UUID"},
            "decision": {"type": "string"},
            "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 900},
        },
        "required": ["session", "decision"],
    },
)
def answer_decision(session: str, decision: str, wait_seconds: int = 0):
    target = _session(session)
    if target.status != CodingSession.STATUS_NEEDS_INPUT:
        raise ValueError("This coding session is not waiting for a decision")
    turn = CodingSessionService.start_turn(
        target,
        f"Decision from the user: {decision.strip()}",
        source=CodingTurn.SOURCE_DECISION,
    )
    payload = _wait_for_turn(target, turn, wait_seconds)
    payload["delegated_turn_id"] = str(turn.pk)
    return payload


@register_function(
    manifest_id="coding_sessions.stop_session",
    module="coding_sessions",
    description="Explicitly stop a persistent Codex coding session and its direct terminal.",
    params_schema={
        "type": "object",
        "properties": {"session": {"type": "string", "description": "Coding session display name or UUID"}},
        "required": ["session"],
    },
)
def stop_session(session: str):
    return CodingSessionService.stop(_session(session))


@register_function(
    manifest_id="coding_sessions.resume_session",
    module="coding_sessions",
    description="Resume a stopped persistent Codex coding session with its saved thread and history.",
    params_schema={
        "type": "object",
        "properties": {"session": {"type": "string", "description": "Coding session display name or UUID"}},
        "required": ["session"],
    },
)
def resume_session(session: str):
    return CodingSessionService.resume(_session(session))


@register_function(
    manifest_id="coding_sessions.delegate_feature",
    module="coding_sessions",
    description="Start a durable feature delegation that automatically resumes coding and optionally runs independent QA until it passes or needs a real user decision.",
    params_schema={
        "type": "object",
        "properties": {
            "session": {"type": "string", "description": "Coding session display name or UUID; names returned by list_sessions are accepted directly"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "qa_enabled": {"type": "boolean", "default": True},
            "max_iterations": {"type": "integer", "minimum": 1, "maximum": 12},
            "wait_for_completion": {"type": "boolean", "default": True, "description": "Defaults to true so Corv reports back; set false only when the user asks not to wait"},
        },
        "required": ["session", "title", "description", "acceptance_criteria", "qa_enabled"],
    },
)
def delegate_feature(
    session: str,
    title: str,
    description: str,
    acceptance_criteria: list[str],
    qa_enabled: bool = True,
    max_iterations: int = 6,
    wait_for_completion: bool = True,
):
    delegation = FeatureDelegationService.create(
        _session(session),
        title=title,
        description=description,
        acceptance_criteria=acceptance_criteria,
        qa_enabled=qa_enabled,
        max_iterations=max_iterations,
    )
    payload = FeatureDelegationService.payload(delegation)
    payload["wait_for_completion"] = bool(wait_for_completion)
    return payload


@register_function(
    manifest_id="coding_sessions.list_feature_delegations",
    module="coding_sessions",
    description="List durable feature delegations and their coding/QA state.",
    params_schema={"type": "object", "properties": {"session": {"type": "string"}}},
)
def list_feature_delegations(session: str = ""):
    queryset = FeatureDelegation.objects.select_related("session__machine")
    if session:
        queryset = queryset.filter(session=_session(session))
    return {
        "delegations": [
            FeatureDelegationService.payload(item, include_history=False)
            for item in queryset[:50]
        ]
    }


@register_function(
    manifest_id="coding_sessions.get_feature_delegation",
    module="coding_sessions",
    description="Get feature progress, coder results, QA verdicts/evidence, or a pending decision.",
    params_schema={
        "type": "object",
        "properties": {"delegation": {"type": "string"}},
        "required": ["delegation"],
    },
)
def get_feature_delegation(delegation: str):
    return FeatureDelegationService.payload(_delegation(delegation))


@register_function(
    manifest_id="coding_sessions.resume_feature_delegation",
    module="coding_sessions",
    description="Resume a waiting, failed, or stopped feature delegation. Use mode='qa' to retry blocked QA without starting another coding cycle, or mode='coding' when application changes are required.",
    params_schema={
        "type": "object",
        "properties": {
            "delegation": {"type": "string"},
            "decision": {"type": "string"},
            "mode": {"type": "string", "enum": ["auto", "qa", "coding"], "default": "auto"},
        },
        "required": ["delegation"],
    },
)
def resume_feature_delegation(delegation: str, decision: str = "", mode: str = "auto"):
    item = _delegation(delegation)
    FeatureDelegationService.resume(item, decision, mode=mode)
    item.refresh_from_db()
    return FeatureDelegationService.payload(item)


@register_function(
    manifest_id="coding_sessions.stop_feature_delegation",
    module="coding_sessions",
    description="Explicitly stop an active durable feature delegation.",
    params_schema={
        "type": "object",
        "properties": {"delegation": {"type": "string"}},
        "required": ["delegation"],
    },
)
def stop_feature_delegation(delegation: str):
    item = _delegation(delegation)
    FeatureDelegationService.stop(item)
    item.refresh_from_db()
    return FeatureDelegationService.payload(item)


@register_function(manifest_id="coding_sessions.list_conversation_delegations", module="coding_sessions", description="List all Codex delegations spawned from the current chat or call, including concurrent work, status, ids, questions, and wait state.", params_schema={"type":"object","properties":{"include_finished":{"type":"boolean","default":True}}})
def list_conversation_delegations(include_finished: bool = True):
    return {"conversation_context_required": True, "include_finished": bool(include_finished)}

@register_function(manifest_id="coding_sessions.set_conversation_delegation_wait", module="coding_sessions", description="Start, interrupt, or resume waiting for one specific active delegation in the current chat or call.", params_schema={"type":"object","properties":{"delegation":{"type":"string"},"waiting":{"type":"boolean"}},"required":["delegation","waiting"]})
def set_conversation_delegation_wait(delegation: str, waiting: bool):
    return {"conversation_context_required": True, "delegation": delegation, "waiting": bool(waiting)}
