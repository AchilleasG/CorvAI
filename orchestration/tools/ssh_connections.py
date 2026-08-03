from uuid import UUID

from django.db.models import Q

from orchestration.registry import register_function
from ssh_connections.models import SshCommandRecord, SshMachine
from ssh_connections.services import SshConnectionManager


def _machine(value: str) -> SshMachine:
    value = (value or "").strip()
    if not value:
        raise ValueError("Machine name or id is required")
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


def _summary(machine: SshMachine) -> dict:
    status = SshConnectionManager.status(machine)
    return {
        "id": str(machine.pk),
        "name": machine.name,
        "target": f"{machine.username}@{machine.host}:{machine.port}",
        "connected": status["connected"],
        "allow_ai_commands": machine.allow_ai_commands,
        "host_key_fingerprint": machine.host_key_fingerprint or None,
        "notes": machine.notes,
    }


@register_function(
    manifest_id="ssh_connections.list_machines",
    module="ssh_connections",
    description="List saved SSH machines and their connection state.",
    params_schema={"type": "object", "properties": {}},
)
def list_machines():
    return {"machines": [_summary(machine) for machine in SshMachine.objects.all()]}


@register_function(
    manifest_id="ssh_connections.connect",
    module="ssh_connections",
    description="Open and retain an SSH connection to a saved machine.",
    params_schema={"type": "object", "properties": {"machine": {"type": "string"}}, "required": ["machine"]},
)
def connect(machine: str):
    target = _machine(machine)
    if not target.allow_ai_commands:
        raise PermissionError(f"AI command execution is disabled for machine '{target.name}'")
    SshConnectionManager.connect(target)
    return _summary(target)


@register_function(
    manifest_id="ssh_connections.disconnect",
    module="ssh_connections",
    description="Close the retained SSH connection to a saved machine.",
    params_schema={"type": "object", "properties": {"machine": {"type": "string"}}, "required": ["machine"]},
)
def disconnect(machine: str):
    target = _machine(machine)
    SshConnectionManager.disconnect(target)
    return _summary(target)


@register_function(
    manifest_id="ssh_connections.run_command",
    module="ssh_connections",
    description="Run a command in a named persistent shell session on a saved SSH machine.",
    params_schema={
        "type": "object",
        "properties": {
            "machine": {"type": "string"},
            "command": {"type": "string"},
            "session_name": {"type": "string", "description": "Persistent shell name; defaults to Corv"},
            "timeout_seconds": {"type": "integer"},
        },
        "required": ["machine", "command"],
    },
)
def run_command(machine: str, command: str, timeout_seconds: int | None = None, session_name: str = "Corv"):
    target = _machine(machine)
    if not target.allow_ai_commands:
        raise PermissionError(f"AI command execution is disabled for machine '{target.name}'")
    terminal = SshConnectionManager.get_or_create_named_terminal(target, session_name)
    return SshConnectionManager.run_terminal_command(
        target,
        terminal.id,
        command,
        source=SshCommandRecord.SOURCE_ASSISTANT,
        timeout_seconds=timeout_seconds,
    )
