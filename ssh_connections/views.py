from uuid import UUID

from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from ssh_connections.models import SshMachine
from ssh_connections.schemas import SshCommandIn, SshMachineIn, SshMachineUpdate, SshTerminalSessionIn
from ssh_connections.services import SshConnectionManager


router = Router(tags=["SSH Connections"])


def machine_payload(machine: SshMachine) -> dict:
    status = SshConnectionManager.status(machine)
    return {
        "id": str(machine.pk),
        "name": machine.name,
        "host": machine.host,
        "port": machine.port,
        "username": machine.username,
        "auth_type": machine.auth_type,
        "has_credentials": machine.has_credentials,
        "allow_ai_commands": machine.allow_ai_commands,
        "is_default": machine.is_default,
        "connect_timeout_seconds": machine.connect_timeout_seconds,
        "command_timeout_seconds": machine.command_timeout_seconds,
        "keepalive_seconds": machine.keepalive_seconds,
        "notes": machine.notes,
        "host_key_fingerprint": machine.host_key_fingerprint or None,
        "connected": status["connected"],
        "connected_for_seconds": status["connected_for_seconds"],
        "last_connected_at": machine.last_connected_at.isoformat() if machine.last_connected_at else None,
        "last_error": machine.last_error,
        "created_at": machine.created_at.isoformat() if machine.created_at else None,
        "updated_at": machine.updated_at.isoformat() if machine.updated_at else None,
    }


@router.get("/machines")
def list_machines(request):
    return {"machines": [machine_payload(machine) for machine in SshMachine.objects.order_by("-is_default", "name")]}


@router.post("/machines")
@transaction.atomic
def create_machine(request, payload: SshMachineIn):
    if payload.auth_type not in dict(SshMachine.AUTH_CHOICES):
        raise HttpError(400, "Invalid authentication type")
    machine = SshMachine(
        name=payload.name.strip(),
        host=payload.host.strip(),
        port=payload.port,
        username=payload.username.strip(),
        auth_type=payload.auth_type,
        allow_ai_commands=payload.allow_ai_commands,
        is_default=payload.is_default,
        connect_timeout_seconds=payload.connect_timeout_seconds,
        command_timeout_seconds=payload.command_timeout_seconds,
        keepalive_seconds=payload.keepalive_seconds,
        notes=payload.notes,
    )
    if machine.is_default and not machine.allow_ai_commands:
        raise HttpError(400, "The default machine must allow Corv command execution")
    if machine.is_default:
        SshMachine.objects.filter(is_default=True).update(is_default=False)
    machine.full_clean(exclude=["credential_encrypted"])
    machine.set_credentials(
        password=payload.password,
        private_key=payload.private_key,
        passphrase=payload.passphrase,
    )
    machine.save()
    return machine_payload(machine)


@router.patch("/machines/{machine_id}")
@transaction.atomic
def update_machine(request, machine_id: UUID, payload: SshMachineUpdate):
    machine = get_object_or_404(SshMachine, pk=machine_id)
    connection_fields = {"host", "port", "username", "auth_type"}
    changed_connection = False
    auth_changed = False
    for field in (
        "name", "host", "port", "username", "auth_type", "allow_ai_commands", "is_default",
        "connect_timeout_seconds", "command_timeout_seconds", "keepalive_seconds", "notes",
    ):
        value = getattr(payload, field)
        if value is not None:
            if field in {"name", "host", "username"}:
                value = value.strip()
            if field == "auth_type" and value not in dict(SshMachine.AUTH_CHOICES):
                raise HttpError(400, "Invalid authentication type")
            if field == "auth_type" and machine.auth_type != value:
                auth_changed = True
            if field in connection_fields and getattr(machine, field) != value:
                changed_connection = True
            setattr(machine, field, value)
    credential_supplied = any(
        value is not None for value in (payload.password, payload.private_key, payload.passphrase)
    )
    if credential_supplied:
        machine.set_credentials(
            password=payload.password or "",
            private_key=payload.private_key or "",
            passphrase=payload.passphrase or "",
        )
        changed_connection = True
    elif auth_changed:
        machine.credential_encrypted = ""
    if payload.reset_host_key:
        machine.host_key_fingerprint = ""
        changed_connection = True
    if not machine.allow_ai_commands:
        machine.is_default = False
    if machine.is_default:
        SshMachine.objects.filter(is_default=True).exclude(pk=machine.pk).update(is_default=False)
    machine.full_clean(exclude=["credential_encrypted"])
    machine.save()
    if changed_connection:
        SshConnectionManager.disconnect(machine)
    return machine_payload(machine)


@router.delete("/machines/{machine_id}")
def delete_machine(request, machine_id: UUID):
    machine = get_object_or_404(SshMachine, pk=machine_id)
    SshConnectionManager.disconnect(machine)
    machine.delete()
    return {"ok": True}


@router.post("/machines/{machine_id}/connect")
def connect_machine(request, machine_id: UUID):
    machine = get_object_or_404(SshMachine, pk=machine_id)
    try:
        SshConnectionManager.connect(machine)
        machine.refresh_from_db()
        return machine_payload(machine)
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.post("/machines/{machine_id}/disconnect")
def disconnect_machine(request, machine_id: UUID):
    machine = get_object_or_404(SshMachine, pk=machine_id)
    SshConnectionManager.disconnect(machine)
    return machine_payload(machine)


@router.post("/machines/{machine_id}/commands")
def run_command(request, machine_id: UUID, payload: SshCommandIn):
    machine = get_object_or_404(SshMachine, pk=machine_id)
    try:
        return SshConnectionManager.run_command(
            machine,
            payload.command,
            timeout_seconds=payload.timeout_seconds,
        )
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.get("/machines/{machine_id}/sessions")
def list_terminal_sessions(request, machine_id: UUID):
    machine = get_object_or_404(SshMachine, pk=machine_id)
    return {"sessions": SshConnectionManager.list_terminal_sessions(machine)}


@router.post("/machines/{machine_id}/sessions")
def create_terminal_session(request, machine_id: UUID, payload: SshTerminalSessionIn):
    machine = get_object_or_404(SshMachine, pk=machine_id)
    try:
        return SshConnectionManager.create_terminal_session(machine, name=payload.name)
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.delete("/machines/{machine_id}/sessions/{session_id}")
def close_terminal_session(request, machine_id: UUID, session_id: UUID):
    machine = get_object_or_404(SshMachine, pk=machine_id)
    try:
        return SshConnectionManager.close_terminal_session(machine, str(session_id))
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.post("/machines/{machine_id}/sessions/{session_id}/commands")
def run_terminal_command(request, machine_id: UUID, session_id: UUID, payload: SshCommandIn):
    machine = get_object_or_404(SshMachine, pk=machine_id)
    try:
        return SshConnectionManager.run_terminal_command(
            machine,
            str(session_id),
            payload.command,
            timeout_seconds=payload.timeout_seconds,
        )
    except Exception as exc:
        raise HttpError(400, str(exc))


@router.get("/machines/{machine_id}/history")
def command_history(request, machine_id: UUID, limit: int = 50):
    machine = get_object_or_404(SshMachine, pk=machine_id)
    rows = machine.command_records.all()[: max(1, min(limit, 200))]
    return {
        "commands": [
            {
                "id": str(row.pk),
                "command": row.command,
                "source": row.source,
                "exit_status": row.exit_status,
                "duration_ms": row.duration_ms,
                "succeeded": row.succeeded,
                "error_summary": row.error_summary,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }
