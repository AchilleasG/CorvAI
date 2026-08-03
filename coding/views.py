from uuid import UUID
from pathlib import Path

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from coding.models import CodingSession, CodingTurn, FeatureDelegation, FeatureQaRun
from coding.auth import CodexDeviceAuthService
from coding.delegations import FeatureDelegationService
from coding.schemas import (
    CodingSessionIn,
    CodingTaskIn,
    CodingTerminalInput,
    FeatureDelegationIn,
    FeatureDelegationResumeIn,
)
from coding.services import CodingSessionService
from ssh_connections.models import SshMachine


router = Router(tags=["Coding Sessions"])


@router.get("/status")
def coding_status(request):
    return CodingSessionService.cli_status()


@router.get("/auth/device")
def device_auth_status(request):
    return CodexDeviceAuthService.payload()


@router.post("/auth/device")
def start_device_auth(request):
    try:
        return CodexDeviceAuthService.start()
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.post("/auth/device/cancel")
def cancel_device_auth(request):
    return CodexDeviceAuthService.cancel()


@router.post("/auth/logout")
def logout_codex(request):
    try:
        return CodexDeviceAuthService.logout()
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.get("/sessions")
def list_sessions(request):
    sessions = CodingSession.objects.select_related("machine").all()
    return {"sessions": [CodingSessionService.session_payload(session, include_turns=False) for session in sessions]}


@router.post("/sessions")
def create_session(request, payload: CodingSessionIn):
    machine = get_object_or_404(SshMachine, pk=payload.machine_id)
    if not machine.allow_ai_commands:
        raise HttpError(400, "Enable Corv command access on this SSH machine first")
    name = payload.name.strip()
    if not name:
        raise HttpError(400, "Session name is required")
    remote_directory = payload.remote_working_directory.strip() or "~"
    session = CodingSession.objects.create(
        name=name,
        machine=machine,
        remote_working_directory=remote_directory,
    )
    try:
        CodingSessionService.prepare_workspace(session)
    except Exception as exc:
        session.delete()
        raise HttpError(400, str(exc))
    return CodingSessionService.session_payload(session)


@router.get("/sessions/{session_id}")
def get_session(request, session_id: UUID):
    session = get_object_or_404(CodingSession.objects.select_related("machine"), pk=session_id)
    return CodingSessionService.session_payload(session)


@router.get("/sessions/{session_id}/logs")
def get_session_logs(request, session_id: UUID):
    session = get_object_or_404(CodingSession, pk=session_id)
    return CodingSessionService.live_logs_payload(session)


@router.delete("/sessions/{session_id}")
def delete_session(request, session_id: UUID):
    session = get_object_or_404(CodingSession, pk=session_id)
    if session.status != CodingSession.STATUS_STOPPED:
        raise HttpError(400, "Stop the coding session before deleting it")
    CodingSessionService.delete(session)
    return {"ok": True}


@router.post("/sessions/{session_id}/tasks")
def start_task(request, session_id: UUID, payload: CodingTaskIn):
    session = get_object_or_404(CodingSession.objects.select_related("machine"), pk=session_id)
    try:
        turn = CodingSessionService.start_turn(session, payload.prompt, source=payload.source)
        return CodingSessionService.turn_payload(turn)
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.post("/sessions/{session_id}/decisions")
def answer_decision(request, session_id: UUID, payload: CodingTaskIn):
    session = get_object_or_404(CodingSession.objects.select_related("machine"), pk=session_id)
    if session.status != CodingSession.STATUS_NEEDS_INPUT:
        raise HttpError(400, "This coding session is not waiting for a decision")
    try:
        prompt = f"Decision from the user: {payload.prompt.strip()}"
        turn = CodingSessionService.start_turn(session, prompt, source=CodingTurn.SOURCE_DECISION)
        return CodingSessionService.turn_payload(turn)
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.post("/sessions/{session_id}/terminal/start")
def start_terminal(request, session_id: UUID):
    session = get_object_or_404(CodingSession.objects.select_related("machine"), pk=session_id)
    try:
        return CodingSessionService.start_terminal(session)
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.get("/sessions/{session_id}/terminal")
def get_terminal(request, session_id: UUID):
    session = get_object_or_404(CodingSession, pk=session_id)
    return CodingSessionService.terminal_payload(session)


@router.post("/sessions/{session_id}/terminal/input")
def terminal_input(request, session_id: UUID, payload: CodingTerminalInput):
    session = get_object_or_404(CodingSession, pk=session_id)
    try:
        return CodingSessionService.terminal_input(session, text=payload.text, key=payload.key)
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.post("/sessions/{session_id}/terminal/close")
def close_terminal(request, session_id: UUID):
    session = get_object_or_404(CodingSession, pk=session_id)
    return CodingSessionService.close_terminal(session)


@router.post("/sessions/{session_id}/stop")
def stop_session(request, session_id: UUID):
    session = get_object_or_404(CodingSession.objects.select_related("machine"), pk=session_id)
    return CodingSessionService.stop(session)


@router.get("/delegations")
def list_delegations(request, session_id: str = ""):
    delegations = FeatureDelegation.objects.select_related("session__machine")
    if session_id:
        delegations = delegations.filter(session_id=session_id)
    return {
        "delegations": [
            FeatureDelegationService.payload(item, include_history=False)
            for item in delegations[:100]
        ]
    }


@router.post("/sessions/{session_id}/delegations")
def create_delegation(request, session_id: UUID, payload: FeatureDelegationIn):
    session = get_object_or_404(CodingSession.objects.select_related("machine"), pk=session_id)
    try:
        delegation = FeatureDelegationService.create(
            session,
            title=payload.title,
            description=payload.description,
            acceptance_criteria=payload.acceptance_criteria,
            qa_enabled=payload.qa_enabled,
            max_iterations=payload.max_iterations,
        )
        return FeatureDelegationService.payload(delegation)
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.get("/delegations/{delegation_id}")
def get_delegation(request, delegation_id: UUID):
    delegation = get_object_or_404(
        FeatureDelegation.objects.select_related("session__machine"), pk=delegation_id
    )
    return FeatureDelegationService.payload(delegation)


@router.post("/delegations/{delegation_id}/resume")
def resume_delegation(request, delegation_id: UUID, payload: FeatureDelegationResumeIn):
    delegation = get_object_or_404(
        FeatureDelegation.objects.select_related("session__machine"), pk=delegation_id
    )
    try:
        FeatureDelegationService.resume(delegation, payload.decision)
        delegation.refresh_from_db()
        return FeatureDelegationService.payload(delegation)
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.post("/delegations/{delegation_id}/stop")
def stop_delegation(request, delegation_id: UUID):
    delegation = get_object_or_404(
        FeatureDelegation.objects.select_related("session__machine"), pk=delegation_id
    )
    FeatureDelegationService.stop(delegation)
    delegation.refresh_from_db()
    return FeatureDelegationService.payload(delegation)


@router.get("/qa-runs/{qa_run_id}/evidence/{evidence_index}")
def qa_evidence(request, qa_run_id: UUID, evidence_index: int):
    qa_run = get_object_or_404(
        FeatureQaRun.objects.select_related("delegation__session"), pk=qa_run_id
    )
    if evidence_index < 0 or evidence_index >= len(qa_run.evidence):
        raise HttpError(404, "QA evidence was not found")
    candidate = Path(str(qa_run.evidence[evidence_index])).resolve()
    evidence_root = (
        CodingSessionService.workspace_dir(qa_run.delegation.session)
        / "qa-evidence"
        / str(qa_run.pk)
    ).resolve()
    if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HttpError(404, "This QA evidence is not an image")
    if evidence_root not in candidate.parents or not candidate.is_file():
        raise HttpError(404, "QA screenshot was not found")
    return FileResponse(candidate.open("rb"), content_type=f"image/{'jpeg' if candidate.suffix.lower() in {'.jpg', '.jpeg'} else candidate.suffix.lower()[1:]}")
