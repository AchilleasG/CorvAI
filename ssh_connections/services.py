from __future__ import annotations

import base64
import hashlib
import io
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from django.utils import timezone

from ssh_connections.models import SshCommandRecord, SshMachine


MAX_OUTPUT_BYTES = 256 * 1024


def _paramiko():
    try:
        import paramiko
    except ImportError as exc:  # pragma: no cover - deployment configuration
        raise RuntimeError("SSH support is unavailable: install the paramiko dependency") from exc
    return paramiko


def key_fingerprint(key: Any) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


class PinnedHostKeyPolicy:
    def __init__(self, machine: SshMachine):
        self.machine = machine

    def missing_host_key(self, client, hostname, key):
        paramiko = _paramiko()
        actual = key_fingerprint(key)
        expected = (self.machine.host_key_fingerprint or "").strip()
        if expected and expected != actual:
            raise paramiko.SSHException(
                f"Host key mismatch for {self.machine.name}: expected {expected}, received {actual}"
            )
        if not expected:
            SshMachine.objects.filter(pk=self.machine.pk).update(host_key_fingerprint=actual)
            self.machine.host_key_fingerprint = actual
        client.get_host_keys().add(hostname, key.get_name(), key)


@dataclass
class OpenSshSession:
    client: Any
    connected_at: float
    last_used_at: float


@dataclass
class OpenTerminalSession:
    id: str
    machine_key: str
    name: str
    channel: Any
    created_at: float
    last_used_at: float
    cwd: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)


class SshConnectionManager:
    _sessions: dict[str, OpenSshSession] = {}
    _terminals: dict[str, OpenTerminalSession] = {}
    _lock = threading.RLock()

    @classmethod
    def _session_key(cls, machine: SshMachine) -> str:
        return str(machine.pk)

    @classmethod
    def is_connected(cls, machine: SshMachine) -> bool:
        key = cls._session_key(machine)
        with cls._lock:
            session = cls._sessions.get(key)
            transport = session.client.get_transport() if session else None
            active = bool(transport and transport.is_active())
            if session and not active:
                try:
                    session.client.close()
                finally:
                    cls._sessions.pop(key, None)
            return active

    @classmethod
    def _load_private_key(cls, key_text: str, passphrase: str = ""):
        paramiko = _paramiko()
        errors = []
        key_classes = [paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey]
        dss_key = getattr(paramiko, "DSSKey", None)
        if dss_key:
            key_classes.append(dss_key)
        for key_class in key_classes:
            try:
                return key_class.from_private_key(io.StringIO(key_text), password=passphrase or None)
            except Exception as exc:
                errors.append(str(exc))
        raise ValueError("Private key could not be parsed or its passphrase is incorrect")

    @classmethod
    def connect(cls, machine: SshMachine, *, force: bool = False) -> dict:
        paramiko = _paramiko()
        key = cls._session_key(machine)
        with cls._lock:
            if not force and cls.is_connected(machine):
                return cls.status(machine)
            cls.disconnect(machine)

            credentials = machine.get_credentials()
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(PinnedHostKeyPolicy(machine))
            kwargs: dict[str, Any] = {
                "hostname": machine.host,
                "port": machine.port,
                "username": machine.username,
                "timeout": machine.connect_timeout_seconds,
                "banner_timeout": machine.connect_timeout_seconds,
                "auth_timeout": machine.connect_timeout_seconds,
            }
            if machine.auth_type == SshMachine.AUTH_PASSWORD:
                password = credentials.get("password", "")
                if not password:
                    raise ValueError("This machine has no saved password")
                kwargs.update(password=password, look_for_keys=False, allow_agent=False)
            elif machine.auth_type == SshMachine.AUTH_PRIVATE_KEY:
                key_text = credentials.get("private_key", "")
                if not key_text:
                    raise ValueError("This machine has no saved private key")
                kwargs.update(
                    pkey=cls._load_private_key(key_text, credentials.get("passphrase", "")),
                    look_for_keys=False,
                    allow_agent=False,
                )
            else:
                kwargs.update(look_for_keys=True, allow_agent=True)

            try:
                client.connect(**kwargs)
                transport = client.get_transport()
                if not transport or not transport.is_active():
                    raise RuntimeError("SSH transport did not become active")
                transport.set_keepalive(machine.keepalive_seconds)
                now = time.monotonic()
                cls._sessions[key] = OpenSshSession(client=client, connected_at=now, last_used_at=now)
                SshMachine.objects.filter(pk=machine.pk).update(last_connected_at=timezone.now(), last_error="")
                machine.last_error = ""
                return cls.status(machine)
            except Exception as exc:
                client.close()
                SshMachine.objects.filter(pk=machine.pk).update(last_error=str(exc))
                raise

    @classmethod
    def disconnect(cls, machine: SshMachine) -> dict:
        key = cls._session_key(machine)
        with cls._lock:
            for terminal_id, terminal in list(cls._terminals.items()):
                if terminal.machine_key == key:
                    try:
                        terminal.channel.close()
                    finally:
                        cls._terminals.pop(terminal_id, None)
            session = cls._sessions.pop(key, None)
            if session:
                session.client.close()
        return cls.status(machine)

    @classmethod
    def status(cls, machine: SshMachine) -> dict:
        connected = cls.is_connected(machine)
        session = cls._sessions.get(cls._session_key(machine)) if connected else None
        return {
            "connected": connected,
            "connected_for_seconds": int(time.monotonic() - session.connected_at) if session else None,
            "host_key_fingerprint": machine.host_key_fingerprint or None,
        }

    @classmethod
    def _terminal_payload(cls, terminal: OpenTerminalSession) -> dict:
        active = not terminal.channel.closed and not terminal.channel.exit_status_ready()
        return {
            "id": terminal.id,
            "name": terminal.name,
            "connected": active,
            "cwd": terminal.cwd or None,
            "created_at": terminal.created_at,
            "last_used_at": terminal.last_used_at,
        }

    @classmethod
    def list_terminal_sessions(cls, machine: SshMachine) -> list[dict]:
        machine_key = cls._session_key(machine)
        with cls._lock:
            result = []
            for terminal_id, terminal in list(cls._terminals.items()):
                if terminal.machine_key != machine_key:
                    continue
                if terminal.channel.closed or terminal.channel.exit_status_ready():
                    terminal.channel.close()
                    cls._terminals.pop(terminal_id, None)
                    continue
                result.append(cls._terminal_payload(terminal))
            return sorted(result, key=lambda item: item["created_at"])

    @classmethod
    def create_terminal_session(cls, machine: SshMachine, *, name: str = "Terminal") -> dict:
        if not cls.is_connected(machine):
            cls.connect(machine)
        connection = cls._sessions[cls._session_key(machine)]
        channel = connection.client.invoke_shell(term="dumb", width=160, height=48)
        terminal_id = str(uuid.uuid4())
        now = time.time()
        terminal = OpenTerminalSession(
            id=terminal_id,
            machine_key=cls._session_key(machine),
            name=(name or "Terminal").strip()[:80],
            channel=channel,
            created_at=now,
            last_used_at=now,
        )
        # Suppress prompts and local echo so command results are clean while the
        # channel itself remains a real, stateful login shell.
        channel.send("export PS1=''; unset PROMPT_COMMAND; export TERM=dumb; stty -echo\n")
        time.sleep(0.12)
        while channel.recv_ready():
            channel.recv(32768)
        with cls._lock:
            cls._terminals[terminal_id] = terminal
        return cls._terminal_payload(terminal)

    @classmethod
    def close_terminal_session(cls, machine: SshMachine, terminal_id: str) -> dict:
        with cls._lock:
            terminal = cls._terminals.get(terminal_id)
            if not terminal or terminal.machine_key != cls._session_key(machine):
                raise ValueError("Terminal session was not found or is no longer active")
            terminal.channel.close()
            cls._terminals.pop(terminal_id, None)
        return {"id": terminal_id, "closed": True}

    @classmethod
    def get_or_create_named_terminal(cls, machine: SshMachine, name: str) -> OpenTerminalSession:
        normalized = (name or "Corv").strip()[:80]
        for item in cls.list_terminal_sessions(machine):
            if item["name"].casefold() == normalized.casefold():
                return cls._terminals[item["id"]]
        created = cls.create_terminal_session(machine, name=normalized)
        return cls._terminals[created["id"]]

    @classmethod
    def run_terminal_command(
        cls,
        machine: SshMachine,
        terminal_id: str,
        command: str,
        *,
        source: str = SshCommandRecord.SOURCE_API,
        timeout_seconds: int | None = None,
    ) -> dict:
        command = (command or "").strip()
        if not command:
            raise ValueError("Command cannot be empty")
        if source == SshCommandRecord.SOURCE_ASSISTANT and not machine.allow_ai_commands:
            raise PermissionError(f"AI command execution is disabled for machine '{machine.name}'")
        terminal = cls._terminals.get(terminal_id)
        if not terminal or terminal.machine_key != cls._session_key(machine):
            raise ValueError("Terminal session was not found or is no longer active")
        if terminal.channel.closed or terminal.channel.exit_status_ready():
            cls._terminals.pop(terminal_id, None)
            raise ValueError("Terminal session has closed")

        started = time.monotonic()
        record = SshCommandRecord.objects.create(machine=machine, command=command, source=source)
        token = uuid.uuid4().hex
        marker = re.compile(
            rb"(?:\r?\n)?__CORV_DONE_" + token.encode("ascii") + rb":(-?\d+):(.*?)\r?\n"
        )
        timeout = timeout_seconds or machine.command_timeout_seconds
        deadline = time.monotonic() + timeout
        captured = bytearray()
        scan_tail = b""
        truncated = False

        try:
            with terminal.lock:
                terminal.channel.send(
                    command
                    + "\n"
                    + f"printf '\\n__CORV_DONE_{token}:%s:%s\\n' \"$?\" \"$PWD\"\n"
                )
                match = None
                while not match:
                    if terminal.channel.recv_ready():
                        chunk = terminal.channel.recv(32768)
                        candidate = scan_tail + chunk
                        match = marker.search(candidate)
                        remaining = MAX_OUTPUT_BYTES - len(captured)
                        if remaining > 0:
                            captured.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            truncated = True
                        scan_tail = candidate[-4096:]
                    elif terminal.channel.closed or terminal.channel.exit_status_ready():
                        cls._terminals.pop(terminal_id, None)
                        raise RuntimeError("Remote shell closed before the command completed")
                    elif time.monotonic() >= deadline:
                        terminal.channel.send("\x03")
                        raise TimeoutError(f"Command exceeded its {timeout}s timeout; interrupt was sent")
                    else:
                        time.sleep(0.02)

                exit_status = int(match.group(1))
                terminal.cwd = match.group(2).decode("utf-8", errors="replace")
                terminal.last_used_at = time.time()

            output = marker.sub(b"", bytes(captured)).decode("utf-8", errors="replace")
            duration_ms = int((time.monotonic() - started) * 1000)
            record.exit_status = exit_status
            record.duration_ms = duration_ms
            record.succeeded = exit_status == 0
            record.save(update_fields=["exit_status", "duration_ms", "succeeded"])
            return {
                "machine_id": str(machine.pk),
                "machine_name": machine.name,
                "terminal_session_id": terminal.id,
                "terminal_session_name": terminal.name,
                "cwd": terminal.cwd,
                "command": command,
                "stdout": output,
                "stderr": "",
                "exit_status": exit_status,
                "duration_ms": duration_ms,
                "truncated": truncated,
                "connected": True,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            record.duration_ms = duration_ms
            record.error_summary = str(exc)
            record.save(update_fields=["duration_ms", "error_summary"])
            raise

    @classmethod
    def run_command(
        cls,
        machine: SshMachine,
        command: str,
        *,
        source: str = SshCommandRecord.SOURCE_API,
        timeout_seconds: int | None = None,
    ) -> dict:
        if source == SshCommandRecord.SOURCE_ASSISTANT and not machine.allow_ai_commands:
            raise PermissionError(f"AI command execution is disabled for machine '{machine.name}'")
        terminal = cls.get_or_create_named_terminal(machine, "Corv")
        return cls.run_terminal_command(
            machine,
            terminal.id,
            command,
            source=source,
            timeout_seconds=timeout_seconds,
        )
