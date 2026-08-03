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


def _machine(value: str) -> SshMachine:
    value = (value or "").strip()
    if not value:
        raise ValueError("SSH machine name or id is required")
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
    manifest_id="coding_sessions.create_session",
    module="coding_sessions",
    description="Create a persistent full-access Codex session for a saved SSH machine.",
    params_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "machine": {"type": "string", "description": "Saved SSH machine name or id"},
            "remote_working_directory": {"type": "string"},
        },
        "required": ["name", "machine", "remote_working_directory"],
    },
)
def create_session(name: str, machine: str, remote_working_directory: str = "~"):
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
    description="Delegate coding work to Codex through a persistent session. Returns immediately; use get_session to check completion or a pending decision.",
    params_schema={
        "type": "object",
        "properties": {
            "session": {"type": "string", "description": "Coding session display name or UUID; names returned by list_sessions are accepted directly"},
            "task": {"type": "string"},
            "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 900},
        },
        "required": ["session", "task"],
    },
)
def delegate_task(session: str, task: str, wait_seconds: int = 600):
    target = _session(session)
    turn = CodingSessionService.start_turn(target, task, source=CodingTurn.SOURCE_CORV)
    return _wait_for_turn(target, turn, wait_seconds)


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
def answer_decision(session: str, decision: str, wait_seconds: int = 600):
    target = _session(session)
    if target.status != CodingSession.STATUS_NEEDS_INPUT:
        raise ValueError("This coding session is not waiting for a decision")
    turn = CodingSessionService.start_turn(
        target,
        f"Decision from the user: {decision.strip()}",
        source=CodingTurn.SOURCE_DECISION,
    )
    return _wait_for_turn(target, turn, wait_seconds)


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
):
    delegation = FeatureDelegationService.create(
        _session(session),
        title=title,
        description=description,
        acceptance_criteria=acceptance_criteria,
        qa_enabled=qa_enabled,
        max_iterations=max_iterations,
    )
    return FeatureDelegationService.payload(delegation)


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
    description="Resume a feature delegation after providing the user's decision or after an interruption.",
    params_schema={
        "type": "object",
        "properties": {
            "delegation": {"type": "string"},
            "decision": {"type": "string"},
        },
        "required": ["delegation"],
    },
)
def resume_feature_delegation(delegation: str, decision: str = ""):
    item = _delegation(delegation)
    FeatureDelegationService.resume(item, decision)
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
