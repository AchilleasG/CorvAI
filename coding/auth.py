from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

from django.utils import timezone


ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
# Codex currently describes this as a 9-character code and renders it as
# four characters, a separator, then five characters (for example ABCD-EFGHJ).
DEVICE_CODE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{5}\b")
URL_PATTERN = re.compile(r"https?://[^\s<>]+")


@dataclass
class DeviceAuthAttempt:
    id: str
    process: subprocess.Popen
    status: str
    verification_url: str
    user_code: str
    message: str
    created_at: object
    expires_at: object


class CodexDeviceAuthService:
    _attempt: DeviceAuthAttempt | None = None
    _lock = threading.RLock()

    @staticmethod
    def _codex_path() -> str:
        codex = shutil.which("codex")
        if not codex:
            raise RuntimeError("Codex CLI is not installed in the Corv web container")
        return codex

    @staticmethod
    def _is_authenticated(codex: str | None = None) -> bool:
        executable = codex or shutil.which("codex")
        if not executable:
            return False
        try:
            result = subprocess.run(
                [executable, "login", "status"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _safe_verification_url(text: str) -> str:
        for match in URL_PATTERN.findall(text):
            candidate = match.rstrip(".,;:)]}")
            try:
                hostname = (urlparse(candidate).hostname or "").lower()
            except ValueError:
                continue
            if hostname == "openai.com" or hostname.endswith(".openai.com"):
                return candidate
            if hostname == "chatgpt.com" or hostname.endswith(".chatgpt.com"):
                return candidate
        return ""

    @classmethod
    def parse_device_output(cls, text: str) -> tuple[str, str, int]:
        clean = ANSI_ESCAPE.sub("", text)
        verification_url = cls._safe_verification_url(clean)
        code_match = DEVICE_CODE.search(clean)
        minutes_match = re.search(r"expires?\s+in\s+(\d+)\s+minutes?", clean, re.IGNORECASE)
        expires_minutes = int(minutes_match.group(1)) if minutes_match else 15
        return verification_url, code_match.group(0) if code_match else "", expires_minutes

    @classmethod
    def payload(cls, attempt: DeviceAuthAttempt | None = None) -> dict:
        with cls._lock:
            current = attempt or cls._attempt
            if not current:
                return {
                    "active": False,
                    "id": None,
                    "status": "idle",
                    "verification_url": "",
                    "user_code": "",
                    "message": "No Codex login is in progress.",
                    "created_at": None,
                    "expires_at": None,
                }
            if current.status in {"starting", "waiting"} and timezone.now() >= current.expires_at:
                cls._cancel_locked(current, "expired")
            return {
                "active": current.status in {"starting", "waiting"},
                "id": current.id,
                "status": current.status,
                "verification_url": current.verification_url,
                "user_code": current.user_code,
                "message": current.message,
                "created_at": current.created_at.isoformat(),
                "expires_at": current.expires_at.isoformat(),
            }

    @classmethod
    def start(cls) -> dict:
        codex = cls._codex_path()
        with cls._lock:
            if cls._attempt and cls._attempt.status in {"starting", "waiting"}:
                return cls.payload(cls._attempt)
            if cls._is_authenticated(codex):
                return {
                    "active": False,
                    "id": None,
                    "status": "succeeded",
                    "verification_url": "",
                    "user_code": "",
                    "message": "Codex CLI is already authenticated.",
                    "created_at": None,
                    "expires_at": None,
                }
            process = subprocess.Popen(
                [codex, "login", "--device-auth"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
                env=os.environ.copy(),
            )
            now = timezone.now()
            attempt = DeviceAuthAttempt(
                id=str(uuid.uuid4()),
                process=process,
                status="starting",
                verification_url="",
                user_code="",
                message="Waiting for Codex to provide a device code…",
                created_at=now,
                expires_at=now + timedelta(minutes=15),
            )
            cls._attempt = attempt
            threading.Thread(target=cls._watch, args=(attempt,), daemon=True).start()
            return cls.payload(attempt)

    @classmethod
    def _watch(cls, attempt: DeviceAuthAttempt):
        output = ""
        try:
            if attempt.process.stdout is not None:
                for line in attempt.process.stdout:
                    output = (output + line)[-16_384:]
                    verification_url, user_code, expires_minutes = cls.parse_device_output(output)
                    with cls._lock:
                        if cls._attempt is not attempt or attempt.status not in {"starting", "waiting"}:
                            continue
                        if verification_url:
                            attempt.verification_url = verification_url
                        if user_code:
                            attempt.user_code = user_code
                        attempt.expires_at = attempt.created_at + timedelta(minutes=expires_minutes)
                        if attempt.verification_url and attempt.user_code:
                            attempt.status = "waiting"
                            attempt.message = "Complete the sign-in with OpenAI, then return to Corv."
                        else:
                            attempt.status = "starting"
                            attempt.message = "Waiting for Codex to provide the verification link and device code…"
            return_code = attempt.process.wait()
            authenticated = return_code == 0 and cls._is_authenticated()
            with cls._lock:
                if cls._attempt is not attempt or attempt.status in {"cancelled", "expired"}:
                    return
                if authenticated:
                    attempt.status = "succeeded"
                    attempt.message = "Codex CLI is authenticated and ready."
                else:
                    attempt.status = "failed"
                    attempt.message = (
                        "Codex device login failed. Confirm device-code login is enabled in your "
                        "ChatGPT security or workspace settings, then try again."
                    )
        except Exception:
            with cls._lock:
                if cls._attempt is attempt and attempt.status not in {"cancelled", "expired"}:
                    attempt.status = "failed"
                    attempt.message = "Codex device login stopped unexpectedly. Please try again."
        finally:
            output = ""

    @classmethod
    def _cancel_locked(cls, attempt: DeviceAuthAttempt, status: str = "cancelled"):
        attempt.status = status
        attempt.message = "Codex login expired." if status == "expired" else "Codex login was cancelled."
        if attempt.process.poll() is None:
            try:
                os.killpg(attempt.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    @classmethod
    def cancel(cls) -> dict:
        with cls._lock:
            if not cls._attempt:
                return cls.payload()
            if cls._attempt.status in {"starting", "waiting"}:
                cls._cancel_locked(cls._attempt)
            return cls.payload(cls._attempt)

    @classmethod
    def logout(cls) -> dict:
        from coding.models import CodingSession, CodingTurn
        from coding.services import CodingSessionService

        running_turn = CodingTurn.objects.filter(
            status__in=[CodingTurn.STATUS_QUEUED, CodingTurn.STATUS_RUNNING]
        ).exists()
        direct_running = any(
            CodingSessionService.tmux_alive(session)
            for session in CodingSession.objects.exclude(tmux_session_name="")
        )
        if running_turn or direct_running:
            raise ValueError("Stop active Codex tasks and direct CLI sessions before logging out")
        codex = cls._codex_path()
        result = subprocess.run(
            [codex, "logout"], capture_output=True, text=True, timeout=30, check=False
        )
        if result.returncode != 0:
            raise RuntimeError("Codex logout failed")
        with cls._lock:
            cls._attempt = None
        return {"authenticated": False, "message": "Codex CLI has been logged out."}
