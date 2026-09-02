from __future__ import annotations

import json
import os
import re
import select
import socketserver
import threading
from pathlib import Path

from django.db import close_old_connections

from coding.models import CodingSession
from ssh_connections.models import SshCommandRecord
from ssh_connections.services import SshConnectionManager


MAX_REQUEST_BYTES = 1024 * 1024
SAFE_TUNNEL_HOST = re.compile(r"[a-zA-Z0-9.:-]+")


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class CodingSshBroker:
    """Local IPC bridge from a Codex workspace to Corv-owned SSH transports."""

    _brokers: dict[str, "CodingSshBroker"] = {}
    _lock = threading.RLock()

    def __init__(self, session: CodingSession, socket_path: Path):
        self.session_id = str(session.pk)
        self.machine = session.machine
        self.socket_path = Path(socket_path).resolve()
        self.server: _ThreadingUnixServer | None = None
        self.thread: threading.Thread | None = None

    @classmethod
    def ensure(cls, session: CodingSession, socket_path: Path) -> "CodingSshBroker":
        key = str(session.pk)
        resolved = Path(socket_path).resolve()
        with cls._lock:
            current = cls._brokers.get(key)
            if current and current.thread and current.thread.is_alive() and current.socket_path == resolved:
                return current
            if current:
                current.close()
            broker = cls(session, resolved)
            broker.start()
            cls._brokers[key] = broker
            return broker

    @classmethod
    def stop(cls, session: CodingSession) -> None:
        with cls._lock:
            broker = cls._brokers.pop(str(session.pk), None)
        if broker:
            broker.close()

    def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.socket_path.exists():
            self.socket_path.unlink()

        broker = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                broker._handle(self)

        self.server = _ThreadingUnixServer(str(self.socket_path), Handler)
        os.chmod(self.socket_path, 0o600)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name=f"coding-ssh-broker-{self.session_id}",
            daemon=True,
        )
        self.thread.start()

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        self.thread = None
        if self.socket_path.exists():
            self.socket_path.unlink()

    @staticmethod
    def _write_json(handler: socketserver.StreamRequestHandler, payload: dict) -> None:
        handler.wfile.write(json.dumps(payload).encode("utf-8") + b"\n")
        handler.wfile.flush()

    def _handle(self, handler: socketserver.StreamRequestHandler) -> None:
        close_old_connections()
        try:
            raw = handler.rfile.readline(MAX_REQUEST_BYTES + 1)
            if not raw or len(raw) > MAX_REQUEST_BYTES:
                raise ValueError("Invalid SSH broker request")
            request = json.loads(raw.decode("utf-8"))
            operation = str(request.get("operation") or "")
            if operation == "command":
                self._handle_command(handler, request)
            elif operation == "tunnel":
                self._handle_tunnel(handler, request)
            else:
                raise ValueError("Unsupported SSH broker operation")
        except Exception as exc:
            try:
                self._write_json(handler, {"ok": False, "error": str(exc)})
            except (BrokenPipeError, OSError):
                pass
        finally:
            close_old_connections()

    def _handle_command(self, handler: socketserver.StreamRequestHandler, request: dict) -> None:
        command = str(request.get("command") or "")
        if not command.strip():
            raise ValueError("Remote command cannot be empty")
        result = SshConnectionManager.run_exec_command(
            self.machine,
            command,
            source=SshCommandRecord.SOURCE_ASSISTANT,
        )
        self._write_json(
            handler,
            {
                "ok": True,
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "exit_status": result.get("exit_status", 1),
                "truncated": bool(result.get("truncated")),
            },
        )

    def _handle_tunnel(self, handler: socketserver.StreamRequestHandler, request: dict) -> None:
        remote_host = str(request.get("remote_host") or "127.0.0.1").strip()
        remote_port = int(request.get("remote_port") or 0)
        if not SAFE_TUNNEL_HOST.fullmatch(remote_host) or not (1 <= remote_port <= 65535):
            raise ValueError("Invalid SSH tunnel destination")
        if not SshConnectionManager.is_connected(self.machine):
            SshConnectionManager.connect(self.machine)
        connection = SshConnectionManager._sessions[str(self.machine.pk)]
        transport = connection.client.get_transport()
        if not transport or not transport.is_active():
            raise RuntimeError("The managed SSH transport is unavailable")
        channel = transport.open_channel(
            "direct-tcpip",
            (remote_host, remote_port),
            ("127.0.0.1", 0),
        )
        self._write_json(handler, {"ok": True})
        local_socket = handler.connection
        try:
            while True:
                readable, _, _ = select.select([local_socket, channel], [], [], 30)
                if not readable:
                    if not transport.is_active() or channel.closed:
                        break
                    continue
                if local_socket in readable:
                    data = local_socket.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in readable:
                    data = channel.recv(65536)
                    if not data:
                        break
                    local_socket.sendall(data)
        finally:
            channel.close()
