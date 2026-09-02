import mimetypes
import re
import tempfile

from pathlib import Path, PurePosixPath
from uuid import UUID

from django.core.files import File
from django.db.models import Q

from coding.files import _store
from orchestration.registry import register_function
from ssh_connections.models import SshCommandRecord, SshMachine
from ssh_connections.services import SshConnectionManager


def _machine(value: str = "") -> SshMachine:
    value = (value or "").strip()
    if not value:
        default = SshMachine.objects.filter(is_default=True, allow_ai_commands=True).first()
        if default:
            return default
        raise ValueError("Machine name or id is required because no default SSH machine is configured")
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
        "is_default": machine.is_default,
        "host_key_fingerprint": machine.host_key_fingerprint or None,
        "notes": machine.notes,
    }


@register_function(
    manifest_id="ssh_connections.list_machines",
    module="ssh_connections",
    description=(
        "List saved SSH machines with exact names, ids, default status, permissions, and operational "
        "notes. Call this before other SSH tools when a requested machine name is uncertain, when the "
        "user asks what is available, or when choosing the most suitable machine for a task."
    ),
    params_schema={"type": "object", "properties": {}},
)
def list_machines():
    return {"machines": [_summary(machine) for machine in SshMachine.objects.order_by("-is_default", "name")]}


@register_function(
    manifest_id="ssh_connections.set_machine_notes",
    module="ssh_connections",
    description=(
        "Add to or replace durable operational notes for a saved SSH machine. Notes are loaded "
        "into Corv's planning context whenever SSH tools are available, so record useful facts "
        "such as capabilities, paths, package-manager behavior, roles, and limitations. Never "
        "store passwords, private keys, tokens, or other secrets."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "machine": {"type": "string", "description": "Saved machine name or id"},
            "notes": {"type": "string", "description": "Durable, concise machine-specific guidance"},
            "mode": {
                "type": "string",
                "enum": ["append", "replace"],
                "default": "append",
                "description": "Append without destroying existing notes, or replace stale notes",
            },
        },
        "required": ["machine", "notes"],
    },
)
def set_machine_notes(machine: str, notes: str, mode: str = "append"):
    target = _machine(machine)
    clean = (notes or "").strip()
    if mode not in {"append", "replace"}:
        raise ValueError("mode must be 'append' or 'replace'")
    if len(clean) > 12000:
        raise ValueError("Machine notes cannot exceed 12,000 characters")
    if mode == "append" and clean:
        existing = target.notes.strip()
        if clean not in existing:
            clean = f"{existing}\n{clean}".strip()
        else:
            clean = existing
    target.notes = clean
    target.save(update_fields=["notes", "updated_at"])
    return _summary(target)


@register_function(
    manifest_id="ssh_connections.connect",
    module="ssh_connections",
    description="Open and retain an SSH connection to a saved machine.",
    params_schema={"type": "object", "properties": {"machine": {"type": "string", "description": "Machine name/id; omit to use the default"}}},
)
def connect(machine: str = ""):
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
    description=(
        "Run one bounded command only when the exact command and path are already known. Do not use this "
        "for finding, locating, searching, or discovering projects, repositories, files, or unknown paths; "
        "use coding_sessions delegation on the requested machine for those tasks and multi-step work."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "machine": {"type": "string", "description": "Machine name/id; omit to use the user's default SSH machine"},
            "command": {"type": "string", "description": "Exact shell command to execute on the selected machine"},
            "session_name": {"type": "string", "description": "Persistent shell name; defaults to Corv"},
            "timeout_seconds": {"type": "integer"},
        },
        "required": ["command"],
    },
)
def run_command(machine: str = "", command: str = "", timeout_seconds: int | None = None, session_name: str = "Corv"):
    target = _machine(machine)
    if not target.allow_ai_commands:
        raise PermissionError(f"AI command execution is disabled for machine '{target.name}'")
    # Sudo can wait indefinitely for terminal input even with a NOPASSWD rule on
    # some interactive shells. Use an isolated exec channel for elevated commands.
    if re.search(r"(^|[;&|(\n]\s*)sudo(?:\s|$)", command):
        return SshConnectionManager.run_exec_command(
            target,
            command,
            source=SshCommandRecord.SOURCE_ASSISTANT,
            timeout_seconds=timeout_seconds,
        )
    terminal = SshConnectionManager.get_or_create_named_terminal(target, session_name)
    return SshConnectionManager.run_terminal_command(
        target,
        terminal.id,
        command,
        source=SshCommandRecord.SOURCE_ASSISTANT,
        timeout_seconds=timeout_seconds,
    )


@register_function(
    manifest_id="ssh_connections.fetch_file",
    module="ssh_connections",
    description=(
        "Fetch a finished file from an SSH machine into Corv Files so it can be attached to the "
        "current chat response. Use after creating PDFs, images, Office documents, archives, or "
        "other artifacts with SSH commands. Omit machine to use the default SSH machine."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "remote_path": {
                "type": "string",
                "description": "Absolute path of the finished remote file",
            },
            "machine": {
                "type": "string",
                "description": "Saved machine name/id; omit to use the default",
            },
            "filename": {
                "type": "string",
                "description": "Optional user-facing filename; defaults to the remote basename",
            },
            "content_type": {
                "type": "string",
                "description": "Optional MIME type; inferred from filename when omitted",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["ssh-artifact"],
            },
            "max_bytes": {
                "type": "integer",
                "minimum": 1,
                "maximum": 52428800,
                "default": 52428800,
            },
        },
        "required": ["remote_path"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "managed_file_id": {"type": "string"},
            "filename": {"type": "string"},
            "download_url": {"type": "string"},
        },
    },
)
def fetch_file(
    remote_path: str,
    machine: str = "",
    filename: str = "",
    content_type: str = "",
    tags: list[str] | None = None,
    max_bytes: int = 50 * 1024 * 1024,
):
    target = _machine(machine)
    if not target.allow_ai_commands:
        raise PermissionError(f"AI file access is disabled for machine '{target.name}'")
    name = Path(filename).name if filename else PurePosixPath(remote_path).name
    if not name or name in {".", ".."}:
        raise ValueError("filename could not be determined; provide a safe filename")
    if tags is not None and (
        not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags)
    ):
        raise ValueError("tags must be a list of strings")
    limit = max(1, min(int(max_bytes), 50 * 1024 * 1024))
    with tempfile.TemporaryDirectory(prefix="corv-ssh-fetch-") as root:
        local_path = Path(root) / name
        transfer = SshConnectionManager.download_file(
            target,
            remote_path,
            local_path,
            max_bytes=limit,
        )
        with local_path.open("rb") as handle:
            item = _store(
                File(handle, name=name),
                name,
                content_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
                None,
                None,
                {
                    "source": "ssh_fetch",
                    "machine_id": str(target.pk),
                    "machine_name": target.name,
                    "remote_path": transfer["remote_path"],
                },
                tags if tags is not None else ["ssh-artifact"],
            )
    return {
        "id": str(item.pk),
        "managed_file_id": str(item.pk),
        "filename": item.filename,
        "content_type": item.content_type,
        "size": item.size,
        "download_url": f"/api/files/{item.pk}/content?download=true",
        "preview_url": f"/api/files/{item.pk}/content",
        "machine_id": str(target.pk),
        "machine_name": target.name,
    }
