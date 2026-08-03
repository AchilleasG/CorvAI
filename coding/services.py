from __future__ import annotations

import base64
import glob
import json
import os
import re
import signal
import shlex
import shutil
import stat
import subprocess
import threading
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from coding.models import CodingSession, CodingTurn, FeatureDelegation, FeatureQaRun
from ssh_connections.models import SshMachine
from ssh_connections.services import SshConnectionManager


MAX_EVENT_LOG_CHARS = 1024 * 1024
MAX_TERMINAL_CHARS = 256 * 1024
MAX_LIVE_LOG_CHARS = 512 * 1024
TERMINAL_KEYS = {"Enter", "Up", "Down", "Left", "Right", "Tab", "Escape", "C-c", "C-d"}


class CodingSessionService:
    _processes: dict[str, subprocess.Popen] = {}
    _active_turns: set[str] = set()
    _lock = threading.RLock()

    @staticmethod
    def _notify(session: CodingSession, event: str, body: str):
        from orchestration.notifications import send_coding_push_to_all

        try:
            send_coding_push_to_all(
                title=f"Coding · {session.name}",
                body=(body or "Coding session update")[:500],
                session_id=str(session.pk),
                event=event,
            )
        except Exception:
            # Notification delivery must never change the coding result.
            pass

    @staticmethod
    def root_dir() -> Path:
        root = Path(getattr(settings, "CORV_CODING_DIR", "/var/lib/corv-coding"))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return root

    @classmethod
    def workspace_dir(cls, session: CodingSession) -> Path:
        return cls.root_dir() / str(session.pk)

    @staticmethod
    def _write_private(path: Path, content: str, executable: bool = False):
        mode = 0o700 if executable else 0o600
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
        finally:
            os.chmod(path, mode)

    @classmethod
    def _host_key_line(cls, machine: SshMachine) -> str:
        SshConnectionManager.connect(machine)
        open_session = SshConnectionManager._sessions[str(machine.pk)]
        transport = open_session.client.get_transport()
        key = transport.get_remote_server_key()
        host = machine.host if machine.port == 22 else f"[{machine.host}]:{machine.port}"
        encoded = base64.b64encode(key.asbytes()).decode("ascii")
        return f"{host} {key.get_name()} {encoded}\n"

    @classmethod
    def prepare_workspace(cls, session: CodingSession) -> tuple[Path, dict[str, str]]:
        machine = session.machine
        if not machine.allow_ai_commands:
            raise PermissionError(
                f"Corv/Codex command access is disabled for SSH machine '{machine.name}'"
            )
        workspace = cls.workspace_dir(session)
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(workspace, 0o700)

        if not re.fullmatch(r"[^\s]+", machine.host) or not re.fullmatch(r"[^\s]+", machine.username):
            raise ValueError("SSH host and username cannot contain whitespace")
        known_hosts = workspace / "known_hosts"
        cls._write_private(known_hosts, cls._host_key_line(machine))
        credentials = machine.get_credentials()
        environment = os.environ.copy()
        ssh_options = [
            "Host target",
            f"  HostName {machine.host}",
            f"  Port {machine.port}",
            f"  User {machine.username}",
            f'  UserKnownHostsFile "{known_hosts}"',
            "  StrictHostKeyChecking yes",
            f"  ConnectTimeout {machine.connect_timeout_seconds}",
            f"  ServerAliveInterval {machine.keepalive_seconds}",
            "  ServerAliveCountMax 3",
        ]
        use_sshpass = False
        sshpass_prompt = ""
        if machine.auth_type == SshMachine.AUTH_PRIVATE_KEY:
            key_text = credentials.get("private_key", "")
            if not key_text:
                raise ValueError("The selected SSH machine has no saved private key")
            identity_file = workspace / "identity"
            cls._write_private(identity_file, key_text.rstrip() + "\n")
            ssh_options.extend(
                [
                    f'  IdentityFile "{identity_file}"',
                    "  IdentitiesOnly yes",
                    "  PreferredAuthentications publickey",
                ]
            )
            passphrase = credentials.get("passphrase", "")
            if passphrase:
                use_sshpass = True
                sshpass_prompt = "Enter passphrase for key"
                environment["SSHPASS"] = passphrase
        elif machine.auth_type == SshMachine.AUTH_PASSWORD:
            password = credentials.get("password", "")
            if not password:
                raise ValueError("The selected SSH machine has no saved password")
            use_sshpass = True
            environment["SSHPASS"] = password
            ssh_options.extend(
                [
                    "  PreferredAuthentications password,keyboard-interactive",
                    "  PubkeyAuthentication no",
                ]
            )
        elif machine.auth_type == SshMachine.AUTH_AGENT:
            agent_socket = environment.get("SSH_AUTH_SOCK", "")
            if not agent_socket or not os.path.exists(agent_socket):
                raise ValueError(
                    "SSH-agent authentication is not available inside the Corv container; use a saved private key or password"
                )

        config_path = workspace / "ssh_config"
        cls._write_private(config_path, "\n".join(ssh_options) + "\n")
        if use_sshpass and sshpass_prompt:
            ssh_prefix = f"sshpass -e -P {shlex.quote(sshpass_prompt)} "
        else:
            ssh_prefix = "sshpass -e " if use_sshpass else ""
        wrapper = workspace / "ssh-target"
        cls._write_private(
            wrapper,
            "#!/bin/sh\n"
            f"exec {ssh_prefix}ssh -F {shlex.quote(str(config_path))} target \"$@\"\n",
            executable=True,
        )
        tunnel_wrapper = workspace / "ssh-tunnel"
        cls._write_private(
            tunnel_wrapper,
            "#!/bin/sh\n"
            f"exec {ssh_prefix}ssh -F {shlex.quote(str(config_path))} -N -o ExitOnForwardFailure=yes -L \"$1\" target\n",
            executable=True,
        )
        browser_wrapper = workspace / "qa-browser"
        cls._write_private(
            browser_wrapper,
            "#!/bin/sh\n"
            f"exec python {shlex.quote(str(Path(settings.BASE_DIR) / 'coding' / 'browser_runner.py'))} \"$@\"\n",
            executable=True,
        )
        remote_dir = session.remote_working_directory.strip() or "~"
        example_command = shlex.quote(f"cd {shlex.quote(remote_dir)} && git status --short")
        agents_text = f"""# Corv remote coding session

All requested code work is on the SSH machine `{machine.name}` ({machine.username}@{machine.host}).
The local directory containing this file is only a control workspace; do not treat it as the target repository.

- Run every repository inspection, edit, build, and test remotely through `./ssh-target`.
- The target working directory is `{remote_dir}`. Prefix remote commands with `cd {shlex.quote(remote_dir)} &&`.
- Example: `./ssh-target {example_command}`.
- Never print, inspect, copy, or disclose SSH credential files or environment variables.
- For browser QA, write a bounded JSON interaction spec and run `./qa-browser SPEC.json --output-dir qa-evidence/NAME`. It supports goto, click, fill, press, select, wait_for, assert_visible, assert_text, assert_url_contains, screenshot, and short sleep actions. If the remote app only listens on localhost, add `"ssh_tunnel": {{"local_port": 18443, "remote_port": 3000}}` and browse `http://127.0.0.1:18443`; the harness opens and cleans up the SSH tunnel.
- Work autonomously, verify changes, preserve unrelated user changes, and report decisions only when they materially alter the requested result.
"""
        (workspace / "AGENTS.md").write_text(agents_text, encoding="utf-8")
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["completed", "needs_input"]},
                "summary": {"type": "string"},
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["status", "summary", "question", "options"],
            "additionalProperties": False,
        }
        (workspace / "result-schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
        qa_schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["passed", "failed", "blocked"]},
                "summary": {"type": "string"},
                "failures": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["status", "summary", "failures", "evidence", "question", "options"],
            "additionalProperties": False,
        }
        (workspace / "qa-result-schema.json").write_text(json.dumps(qa_schema, indent=2), encoding="utf-8")
        if not (workspace / ".git").exists() and shutil.which("git"):
            subprocess.run(["git", "init", "-q", str(workspace)], check=False, timeout=10)
        return workspace, environment

    @staticmethod
    def cli_status() -> dict:
        codex_path = shutil.which("codex")
        tmux_path = shutil.which("tmux")
        ssh_path = shutil.which("ssh")
        sshpass_path = shutil.which("sshpass")
        chromium_path = shutil.which("chromium") or shutil.which("chromium-browser")
        chromedriver_path = shutil.which("chromedriver")
        authenticated = False
        auth_message = "Codex CLI is not installed"
        version = ""
        if codex_path:
            version_result = subprocess.run(
                [codex_path, "--version"], capture_output=True, text=True, timeout=10, check=False
            )
            version = (version_result.stdout or version_result.stderr).strip()
            auth_result = subprocess.run(
                [codex_path, "login", "status"], capture_output=True, text=True, timeout=15, check=False
            )
            authenticated = auth_result.returncode == 0
            auth_message = (auth_result.stdout or auth_result.stderr).strip()
        return {
            "installed": bool(codex_path),
            "authenticated": authenticated,
            "version": version,
            "auth_message": auth_message,
            "tmux_available": bool(tmux_path),
            "ssh_available": bool(ssh_path),
            "password_ssh_available": bool(sshpass_path),
            "browser_qa_available": bool(chromium_path and chromedriver_path),
        }

    @staticmethod
    def managed_codex_command(codex: str, workspace: Path, thread_id: str = "") -> list[str]:
        options = [
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--json",
            "--output-schema",
            str(workspace / "result-schema.json"),
        ]
        if thread_id:
            return [codex, "exec", "resume", *options, thread_id, "-"]
        return [codex, "exec", *options, "-C", str(workspace), "-"]

    @staticmethod
    def interactive_codex_command(codex: str, workspace: Path, thread_id: str = "") -> list[str]:
        options = [
            "--dangerously-bypass-approvals-and-sandbox",
            "--no-alt-screen",
            "-C",
            str(workspace),
        ]
        if thread_id:
            return [codex, "resume", "--include-non-interactive", *options, thread_id]
        return [codex, *options]

    @classmethod
    def tmux_alive(cls, session: CodingSession) -> bool:
        if not session.tmux_session_name or not shutil.which("tmux"):
            return False
        result = subprocess.run(
            ["tmux", "has-session", "-t", session.tmux_session_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0

    @classmethod
    def discover_thread_id(cls, session: CodingSession) -> str:
        if session.codex_thread_id:
            return session.codex_thread_id
        workspace = str(cls.workspace_dir(session).resolve())
        codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        candidates = sorted(
            glob.glob(str(codex_home / "sessions" / "**" / "*.jsonl"), recursive=True),
            key=lambda item: os.path.getmtime(item),
            reverse=True,
        )
        for filename in candidates[:100]:
            try:
                with open(filename, "r", encoding="utf-8") as handle:
                    first = json.loads(handle.readline())
                payload = first.get("payload", {})
                if first.get("type") == "session_meta" and payload.get("cwd") == workspace:
                    thread_id = str(payload.get("id") or "")
                    if thread_id:
                        CodingSession.objects.filter(pk=session.pk).update(codex_thread_id=thread_id)
                        session.codex_thread_id = thread_id
                        return thread_id
            except (OSError, ValueError, TypeError):
                continue
        return ""

    @classmethod
    def session_payload(cls, session: CodingSession, include_turns: bool = True) -> dict:
        direct_running = cls.tmux_alive(session)
        if session.status == CodingSession.STATUS_DIRECT and not direct_running:
            cls.discover_thread_id(session)
            session.status = CodingSession.STATUS_NEEDS_INPUT if session.pending_question else CodingSession.STATUS_READY
            CodingSession.objects.filter(pk=session.pk).update(status=session.status)
        if session.status == CodingSession.STATUS_RUNNING:
            active_turn = session.turns.filter(
                status__in=[CodingTurn.STATUS_QUEUED, CodingTurn.STATUS_RUNNING]
            ).first()
            with cls._lock:
                active_in_process = bool(active_turn and str(active_turn.pk) in cls._active_turns)
            if active_turn and not active_in_process:
                interruption = "Codex was interrupted by a Corv process restart; this session can be continued."
                active_turn.status = CodingTurn.STATUS_FAILED
                active_turn.error = interruption
                active_turn.completed_at = timezone.now()
                active_turn.save(update_fields=["status", "error", "completed_at"])
                session.status = CodingSession.STATUS_FAILED
                session.last_error = interruption
                CodingSession.objects.filter(pk=session.pk).update(
                    status=session.status,
                    last_error=interruption,
                )
        if direct_running and not session.codex_thread_id:
            cls.discover_thread_id(session)
        turns = session.turns.all()[:30] if include_turns else []
        return {
            "id": str(session.pk),
            "name": session.name,
            "machine_id": str(session.machine_id),
            "machine_name": session.machine.name,
            "machine_target": f"{session.machine.username}@{session.machine.host}:{session.machine.port}",
            "remote_working_directory": session.remote_working_directory,
            "status": CodingSession.STATUS_DIRECT if direct_running else session.status,
            "permission_mode": session.permission_mode,
            "codex_thread_id": session.codex_thread_id or None,
            "direct_terminal_running": direct_running,
            "last_summary": session.last_summary,
            "pending_question": session.pending_question,
            "pending_options": session.pending_options,
            "last_error": session.last_error,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "stopped_at": session.stopped_at.isoformat() if session.stopped_at else None,
            "turns": [cls.turn_payload(turn) for turn in turns],
        }

    @classmethod
    def live_logs_payload(cls, session: CodingSession) -> dict:
        entries: list[tuple[object, str, str]] = []
        for turn in session.turns.all()[:30]:
            label = f"CODER · {turn.source.replace('_', ' ')} · {turn.created_at.isoformat()}"
            entries.append((turn.created_at, label, turn.event_log))
        qa_runs = FeatureQaRun.objects.filter(
            delegation__session=session
        ).select_related("delegation")[:30]
        for run in qa_runs:
            label = f"QA · {run.delegation.title} · cycle {run.iteration} · {run.started_at.isoformat()}"
            entries.append((run.started_at, label, run.event_log))
        entries.sort(key=lambda item: item[0])
        content = "\n\n".join(
            f"===== {label} =====\n{log or '[waiting for output…]'}"
            for _created, label, log in entries
        )
        active = session.status in [CodingSession.STATUS_RUNNING]
        return {
            "session_id": str(session.pk),
            "active": active,
            "content": content[-MAX_LIVE_LOG_CHARS:],
            "updated_at": timezone.now().isoformat(),
        }

    @staticmethod
    def turn_payload(turn: CodingTurn) -> dict:
        return {
            "id": str(turn.pk),
            "source": turn.source,
            "prompt": turn.prompt,
            "status": turn.status,
            "codex_thread_id": turn.codex_thread_id or None,
            "summary": turn.summary,
            "question": turn.question,
            "options": turn.options,
            "error": turn.error,
            "started_at": turn.started_at.isoformat() if turn.started_at else None,
            "completed_at": turn.completed_at.isoformat() if turn.completed_at else None,
            "created_at": turn.created_at.isoformat(),
        }

    @classmethod
    def start_turn(cls, session: CodingSession, prompt: str, source: str = CodingTurn.SOURCE_UI) -> CodingTurn:
        from coding.auth import CodexDeviceAuthService

        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("Coding task cannot be empty")
        if session.status == CodingSession.STATUS_STOPPED:
            raise ValueError("This coding session has been stopped")
        if not CodexDeviceAuthService._is_authenticated():
            raise ValueError("Sign in to Codex from the Coding module before delegating a task")
        if cls.tmux_alive(session):
            raise ValueError("Close the direct Codex CLI before delegating a Corv-managed task")
        if source != CodingTurn.SOURCE_FEATURE and session.delegations.filter(
            status__in=[
                FeatureDelegation.STATUS_QUEUED,
                FeatureDelegation.STATUS_CODING,
                FeatureDelegation.STATUS_QA,
                FeatureDelegation.STATUS_FIXING,
                FeatureDelegation.STATUS_NEEDS_INPUT,
            ]
        ).exists():
            raise ValueError("This coding session already has an active feature delegation")
        if session.turns.filter(status__in=[CodingTurn.STATUS_QUEUED, CodingTurn.STATUS_RUNNING]).exists():
            raise ValueError("This coding session already has a task running")
        turn = CodingTurn.objects.create(session=session, prompt=prompt, source=source)
        CodingSession.objects.filter(pk=session.pk).update(
            status=CodingSession.STATUS_RUNNING,
            pending_question="",
            pending_options=[],
            last_error="",
            stopped_at=None,
        )
        worker = threading.Thread(target=cls._run_turn, args=(str(turn.pk),), daemon=True)
        with cls._lock:
            cls._active_turns.add(str(turn.pk))
        worker.start()
        return turn

    @classmethod
    def _run_turn(cls, turn_id: str):
        close_old_connections()
        turn = CodingTurn.objects.select_related("session__machine").get(pk=turn_id)
        session = turn.session
        turn.status = CodingTurn.STATUS_RUNNING
        turn.started_at = timezone.now()
        turn.save(update_fields=["status", "started_at"])
        live_log = ""
        final_message = ""
        try:
            workspace, environment = cls.prepare_workspace(session)
            codex = shutil.which("codex")
            if not codex:
                raise RuntimeError("Codex CLI is not installed in the Corv web container")
            task_prompt = (
                "Act as Corv's coding worker. Complete the following request on the configured remote "
                "machine. Work autonomously and verify the result. If a material decision is truly "
                "required, stop safely and return status needs_input with one concise question and "
                "clear options. Otherwise return status completed with a concise summary and verification.\n\n"
                f"Request:\n{turn.prompt}"
            )
            thread_id = session.codex_thread_id or cls.discover_thread_id(session)
            command = cls.managed_codex_command(codex, workspace, thread_id)
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=workspace,
                env=environment,
                start_new_session=True,
            )
            with cls._lock:
                cls._processes[turn_id] = process
            assert process.stdin is not None
            process.stdin.write(task_prompt)
            process.stdin.close()
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip("\n")
                live_log = f"{live_log}\n{line}".lstrip("\n")[-MAX_EVENT_LOG_CHARS:]
                CodingTurn.objects.filter(pk=turn.pk).update(
                    event_log=live_log
                )
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "thread.started":
                    discovered = str(event.get("thread_id") or "")
                    if discovered:
                        session.codex_thread_id = discovered
                        turn.codex_thread_id = discovered
                        CodingSession.objects.filter(pk=session.pk).update(codex_thread_id=discovered)
                        CodingTurn.objects.filter(pk=turn.pk).update(codex_thread_id=discovered)
                item = event.get("item") or {}
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    final_message = str(item.get("text") or "")
            return_code = process.wait()
            if CodingSession.objects.filter(pk=session.pk, status=CodingSession.STATUS_STOPPED).exists() or CodingTurn.objects.filter(
                pk=turn.pk, status=CodingTurn.STATUS_CANCELLED
            ).exists():
                CodingTurn.objects.filter(pk=turn.pk).update(
                    status=CodingTurn.STATUS_CANCELLED,
                    completed_at=timezone.now(),
                    event_log=live_log,
                )
                return
            if return_code != 0:
                raise RuntimeError(live_log.splitlines()[-1] if live_log else f"Codex exited with status {return_code}")
            try:
                result = json.loads(final_message)
            except (ValueError, TypeError):
                result = {"status": "completed", "summary": final_message, "question": "", "options": []}
            summary = str(result.get("summary") or "").strip()
            question = str(result.get("question") or "").strip()
            options = [str(item) for item in (result.get("options") or [])][:10]
            needs_input = result.get("status") == "needs_input"
            turn.status = CodingTurn.STATUS_NEEDS_INPUT if needs_input else CodingTurn.STATUS_COMPLETED
            turn.summary = summary
            turn.question = question
            turn.options = options
            turn.completed_at = timezone.now()
            turn.event_log = live_log
            turn.save(update_fields=["status", "summary", "question", "options", "completed_at", "event_log", "codex_thread_id"])
            CodingSession.objects.filter(pk=session.pk).update(
                status=CodingSession.STATUS_NEEDS_INPUT if needs_input else CodingSession.STATUS_READY,
                last_summary=summary,
                pending_question=question if needs_input else "",
                pending_options=options if needs_input else [],
                last_error="",
            )
            if turn.source != CodingTurn.SOURCE_FEATURE:
                cls._notify(
                    session,
                    "needs_input" if needs_input else "completed",
                    question if needs_input else (summary or "Codex finished the delegated task."),
                )
        except Exception as exc:
            if CodingSession.objects.filter(pk=session.pk, status=CodingSession.STATUS_STOPPED).exists() or CodingTurn.objects.filter(
                pk=turn.pk, status=CodingTurn.STATUS_CANCELLED
            ).exists():
                CodingTurn.objects.filter(pk=turn.pk).update(
                    status=CodingTurn.STATUS_CANCELLED,
                    completed_at=timezone.now(),
                    event_log=live_log,
                )
            else:
                turn.status = CodingTurn.STATUS_FAILED
                turn.error = str(exc)
                turn.completed_at = timezone.now()
                turn.event_log = live_log
                turn.save(update_fields=["status", "error", "completed_at", "event_log"])
                CodingSession.objects.filter(pk=session.pk).update(
                    status=CodingSession.STATUS_FAILED,
                    last_error=str(exc),
                )
                if turn.source != CodingTurn.SOURCE_FEATURE:
                    cls._notify(session, "failed", f"Codex needs attention: {exc}")
        finally:
            with cls._lock:
                cls._processes.pop(turn_id, None)
                cls._active_turns.discard(turn_id)
            close_old_connections()

    @classmethod
    def start_terminal(cls, session: CodingSession) -> dict:
        from coding.auth import CodexDeviceAuthService

        if session.status == CodingSession.STATUS_STOPPED:
            raise ValueError("This coding session has been stopped")
        if not CodexDeviceAuthService._is_authenticated():
            raise ValueError("Sign in to Codex from the Coding module before opening the CLI")
        if session.turns.filter(status__in=[CodingTurn.STATUS_QUEUED, CodingTurn.STATUS_RUNNING]).exists():
            raise ValueError("Wait for the managed Codex task to finish before opening the direct CLI")
        if session.delegations.filter(
            status__in=[
                FeatureDelegation.STATUS_QUEUED,
                FeatureDelegation.STATUS_CODING,
                FeatureDelegation.STATUS_QA,
                FeatureDelegation.STATUS_FIXING,
                FeatureDelegation.STATUS_NEEDS_INPUT,
            ]
        ).exists():
            raise ValueError("Stop or finish the active feature delegation before opening the direct CLI")
        workspace, environment = cls.prepare_workspace(session)
        if cls.tmux_alive(session):
            return cls.terminal_payload(session)
        codex = shutil.which("codex")
        if not codex or not shutil.which("tmux"):
            raise RuntimeError("Codex CLI and tmux must be installed in the Corv web container")
        tmux_name = session.tmux_session_name or f"corv-codex-{str(session.pk).replace('-', '')[:20]}"
        thread_id = session.codex_thread_id or cls.discover_thread_id(session)
        command = cls.interactive_codex_command(codex, workspace, thread_id)
        tmux_command = [
            "tmux", "new-session", "-d", "-s", tmux_name, "-x", "160", "-y", "44",
            "-c", str(workspace),
        ]
        if environment.get("SSHPASS"):
            tmux_command.extend(["-e", f"SSHPASS={environment['SSHPASS']}"])
        result = subprocess.run(tmux_command + command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "Could not start Codex CLI")
        CodingSession.objects.filter(pk=session.pk).update(
            tmux_session_name=tmux_name,
            status=CodingSession.STATUS_DIRECT,
            last_error="",
        )
        session.tmux_session_name = tmux_name
        session.status = CodingSession.STATUS_DIRECT
        return cls.terminal_payload(session)

    @classmethod
    def terminal_payload(cls, session: CodingSession) -> dict:
        running = cls.tmux_alive(session)
        output = ""
        if running:
            result = subprocess.run(
                ["tmux", "capture-pane", "-p", "-J", "-t", session.tmux_session_name, "-S", "-600"],
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout[-MAX_TERMINAL_CHARS:]
            cls.discover_thread_id(session)
        return {"running": running, "output": output, "thread_id": session.codex_thread_id or None}

    @classmethod
    def terminal_input(cls, session: CodingSession, text: str = "", key: str | None = None) -> dict:
        if not cls.tmux_alive(session):
            raise ValueError("The direct Codex CLI is not running")
        if text:
            buffer_name = f"corv-input-{str(session.pk).replace('-', '')[:20]}"
            subprocess.run(
                ["tmux", "load-buffer", "-b", buffer_name, "-"],
                input=text,
                text=True,
                check=True,
            )
            subprocess.run(
                ["tmux", "paste-buffer", "-b", buffer_name, "-t", session.tmux_session_name, "-d"],
                check=True,
            )
        if key:
            if key not in TERMINAL_KEYS:
                raise ValueError("Unsupported terminal key")
            subprocess.run(["tmux", "send-keys", "-t", session.tmux_session_name, key], check=True)
        return cls.terminal_payload(session)

    @classmethod
    def close_terminal(cls, session: CodingSession) -> dict:
        cls.discover_thread_id(session)
        if cls.tmux_alive(session):
            subprocess.run(["tmux", "kill-session", "-t", session.tmux_session_name], check=False)
        cls.discover_thread_id(session)
        next_status = CodingSession.STATUS_NEEDS_INPUT if session.pending_question else CodingSession.STATUS_READY
        CodingSession.objects.filter(pk=session.pk).update(status=next_status)
        return {"closed": True, "session_id": str(session.pk), "thread_id": session.codex_thread_id or None}

    @classmethod
    def stop(cls, session: CodingSession) -> dict:
        from coding.delegations import FeatureDelegationService

        for delegation in session.delegations.filter(
            status__in=[
                FeatureDelegation.STATUS_QUEUED,
                FeatureDelegation.STATUS_CODING,
                FeatureDelegation.STATUS_QA,
                FeatureDelegation.STATUS_FIXING,
                FeatureDelegation.STATUS_NEEDS_INPUT,
            ]
        ):
            FeatureDelegationService.stop(delegation)
        if cls.tmux_alive(session):
            subprocess.run(["tmux", "kill-session", "-t", session.tmux_session_name], check=False)
        active_turns = list(session.turns.filter(status__in=[CodingTurn.STATUS_QUEUED, CodingTurn.STATUS_RUNNING]))
        with cls._lock:
            for turn in active_turns:
                process = cls._processes.get(str(turn.pk))
                if process and process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
        session.turns.filter(status__in=[CodingTurn.STATUS_QUEUED, CodingTurn.STATUS_RUNNING]).update(
            status=CodingTurn.STATUS_CANCELLED,
            completed_at=timezone.now(),
        )
        session.status = CodingSession.STATUS_STOPPED
        session.stopped_at = timezone.now()
        session.save(update_fields=["status", "stopped_at", "updated_at"])
        return cls.session_payload(session)

    @classmethod
    def cancel_turn(cls, turn: CodingTurn):
        CodingTurn.objects.filter(pk=turn.pk).update(
            status=CodingTurn.STATUS_CANCELLED,
            completed_at=timezone.now(),
        )
        with cls._lock:
            process = cls._processes.get(str(turn.pk))
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    @classmethod
    def delete(cls, session: CodingSession):
        if session.status != CodingSession.STATUS_STOPPED:
            raise ValueError("Stop the coding session before deleting it")
        workspace = cls.workspace_dir(session)
        session.delete()
        if workspace.exists() and workspace.parent.resolve() == cls.root_dir().resolve():
            shutil.rmtree(workspace)
