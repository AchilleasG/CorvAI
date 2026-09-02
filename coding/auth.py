from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

from orchestration.crypto import decrypt_value, encrypt_value


ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
# Codex currently describes this as a 9-character code and renders it as
# four characters, a separator, then five characters (for example ABCD-EFGHJ).
DEVICE_CODE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{5}\b")
URL_PATTERN = re.compile(r"https?://[^\s<>]+")


class CodexAuthService:
    """Persist and select Codex credentials without replacing profile login."""

    MODE_PROFILE = "profile"
    MODE_API_KEY = "api_key"
    MODES = {MODE_PROFILE, MODE_API_KEY}
    MODE_SETTING = "codex_auth_mode"
    API_KEY_SETTING = "codex_api_key_encrypted"

    @staticmethod
    def _setting(key: str, default: str = "") -> str:
        from orchestration.models import OrchestrationSetting

        try:
            return OrchestrationSetting.objects.get(key=key).value or default
        except OrchestrationSetting.DoesNotExist:
            return default

    @staticmethod
    def _set_setting(key: str, value: str):
        from orchestration.models import OrchestrationSetting

        OrchestrationSetting.objects.update_or_create(key=key, defaults={"value": value})

    @classmethod
    def mode(cls) -> str:
        mode = cls._setting(cls.MODE_SETTING, cls.MODE_PROFILE).lower()
        return mode if mode in cls.MODES else cls.MODE_PROFILE

    @classmethod
    def api_key(cls) -> str:
        encrypted = cls._setting(cls.API_KEY_SETTING)
        return decrypt_value(encrypted) if encrypted else ""

    @classmethod
    def api_key_hint(cls) -> str:
        key = cls.api_key()
        return f"••••{key[-4:]}" if key else ""

    @staticmethod
    def _codex_path() -> str:
        codex = shutil.which("codex")
        if not codex:
            raise RuntimeError("Codex CLI is not installed in the Corv web container")
        return codex

    @classmethod
    def api_home(cls) -> str:
        root = os.path.abspath(getattr(settings, "CORV_CODING_DIR", "/var/lib/corv-coding"))
        path = os.path.join(root, ".codex-api-key")
        os.makedirs(path, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
        # Keep conversations and user customization common to both modes while
        # isolating only auth.json, which is what allows instant switching.
        profile_home = os.path.abspath(
            os.environ.get("CODEX_HOME", os.path.join(os.path.expanduser("~"), ".codex"))
        )
        if profile_home != path:
            for name in ("sessions", "archived_sessions", "config.toml", "AGENTS.md", "rules", "skills"):
                source = os.path.join(profile_home, name)
                destination = os.path.join(path, name)
                if os.path.exists(source) and not os.path.lexists(destination):
                    os.symlink(source, destination, target_is_directory=os.path.isdir(source))
        return path

    @staticmethod
    def profile_environment(base: dict[str, str] | None = None) -> dict[str, str]:
        environment = dict(os.environ if base is None else base)
        # An inherited key must not silently override the selected ChatGPT profile.
        environment.pop("OPENAI_API_KEY", None)
        return environment

    @classmethod
    def api_environment(cls, base: dict[str, str] | None = None) -> dict[str, str]:
        environment = dict(os.environ if base is None else base)
        environment.pop("OPENAI_API_KEY", None)
        environment["CODEX_HOME"] = cls.api_home()
        return environment

    @staticmethod
    def _login_status(codex: str, environment: dict[str, str]) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                [codex, "login", "status"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                env=environment,
            )
            return result.returncode == 0, (result.stdout or result.stderr).strip()
        except (OSError, subprocess.TimeoutExpired):
            return False, "Could not check Codex authentication"

    @classmethod
    def profile_status(cls, codex: str | None = None) -> tuple[bool, str]:
        executable = codex or shutil.which("codex")
        if not executable:
            return False, "Codex CLI is not installed"
        return cls._login_status(executable, cls.profile_environment())

    @classmethod
    def _write_api_login(cls, key: str, codex: str | None = None):
        executable = codex or cls._codex_path()
        result = subprocess.run(
            [executable, "login", "--with-api-key"],
            input=key,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=cls.api_environment(),
        )
        if result.returncode != 0:
            raise RuntimeError("Codex rejected the API key login")

    @classmethod
    def api_status(cls, codex: str | None = None, repair: bool = True) -> tuple[bool, str]:
        executable = codex or shutil.which("codex")
        if not executable:
            return False, "Codex CLI is not installed"
        if not cls.api_key():
            return False, "Add an OpenAI API key in Settings"
        authenticated, message = cls._login_status(executable, cls.api_environment())
        if not authenticated and repair:
            cls._write_api_login(cls.api_key(), executable)
            authenticated, message = cls._login_status(executable, cls.api_environment())
        return authenticated, message

    @classmethod
    def selected_status(cls, codex: str | None = None) -> tuple[bool, str]:
        if cls.mode() == cls.MODE_API_KEY:
            return cls.api_status(codex)
        return cls.profile_status(codex)

    _usage_cache: tuple[float, dict] | None = None
    _usage_lock = threading.RLock()

    @classmethod
    def _app_server_rate_limits(cls, codex: str) -> dict:
        process = subprocess.Popen(
            [codex, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=cls.profile_environment(),
        )
        selector = selectors.DefaultSelector()
        try:
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("Codex usage channel could not be opened")
            selector.register(process.stdout, selectors.EVENT_READ)

            def send(payload: dict):
                process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
                process.stdin.flush()

            send({
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "corv", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            })
            deadline = time.monotonic() + 8
            initialized = False
            while time.monotonic() < deadline:
                if not selector.select(timeout=max(0.05, deadline - time.monotonic())):
                    continue
                line = process.stdout.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") == 1 and not initialized:
                    initialized = True
                    send({"method": "initialized"})
                    send({"id": 2, "method": "account/rateLimits/read"})
                elif message.get("id") == 2:
                    return message
            raise RuntimeError("Codex did not return usage in time")
        finally:
            selector.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()

    @staticmethod
    def _usage_window(payload) -> dict | None:
        if not isinstance(payload, dict):
            return None
        used = max(0, min(100, int(payload.get("usedPercent", 0))))
        return {
            "used_percent": used,
            "remaining_percent": 100 - used,
            "resets_at": payload.get("resetsAt"),
            "window_minutes": payload.get("windowDurationMins"),
        }

    @classmethod
    def profile_usage(cls, codex: str | None = None, *, refresh: bool = False) -> dict:
        if cls.mode() != cls.MODE_PROFILE:
            return {"available": False, "reason": "Usage limits are only available for ChatGPT profile login."}
        executable = codex or shutil.which("codex")
        if not executable:
            return {"available": False, "reason": "Codex CLI is not installed."}
        authenticated, _ = cls.profile_status(executable)
        if not authenticated:
            return {"available": False, "reason": "Sign in with your ChatGPT profile to see usage."}
        with cls._usage_lock:
            if not refresh and cls._usage_cache and time.monotonic() - cls._usage_cache[0] < 60:
                return cls._usage_cache[1]
            try:
                response = cls._app_server_rate_limits(executable)
                if response.get("error"):
                    message = str(response["error"].get("message") or "Usage is unavailable.")
                    if "chatgpt authentication required" in message.lower():
                        message = "This profile is using an API key. Sign in with ChatGPT to see profile usage limits."
                    payload = {"available": False, "reason": message}
                else:
                    result = response.get("result") or {}
                    limits = result.get("rateLimitsByLimitId") or {}
                    snapshot = limits.get("codex") if isinstance(limits, dict) else None
                    snapshot = snapshot or result.get("rateLimits") or {}
                    credits = snapshot.get("credits") if isinstance(snapshot, dict) else None
                    payload = {
                        "available": True,
                        "plan_type": snapshot.get("planType"),
                        "limit_name": snapshot.get("limitName"),
                        "primary": cls._usage_window(snapshot.get("primary")),
                        "secondary": cls._usage_window(snapshot.get("secondary")),
                        "credits": {
                            "has_credits": bool(credits.get("hasCredits")),
                            "unlimited": bool(credits.get("unlimited")),
                            "balance": credits.get("balance"),
                        } if isinstance(credits, dict) else None,
                    }
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                payload = {"available": False, "reason": str(exc) or "Usage is temporarily unavailable."}
            cls._usage_cache = (time.monotonic(), payload)
            return payload

    @classmethod
    def is_authenticated(cls, codex: str | None = None) -> bool:
        return cls.selected_status(codex)[0]

    @classmethod
    def process_environment(cls, base: dict[str, str] | None = None) -> dict[str, str]:
        if cls.mode() == cls.MODE_API_KEY:
            authenticated, message = cls.api_status()
            if not authenticated:
                raise RuntimeError(message or "Codex API key authentication is not ready")
            return cls.api_environment(base)
        return cls.profile_environment(base)

    @classmethod
    def settings_payload(cls) -> dict:
        return {
            "codex_auth_mode": cls.mode(),
            "codex_api_key_configured": bool(cls.api_key()),
            "codex_api_key_hint": cls.api_key_hint(),
        }

    @classmethod
    def update(cls, mode: str | None = None, api_key: str | None = None) -> dict:
        normalized_mode = (mode or cls.mode()).lower()
        if normalized_mode not in cls.MODES:
            raise ValueError("Codex authentication mode must be profile or api_key")
        supplied_key = (api_key or "").strip()
        if supplied_key:
            # Validate that the installed CLI accepts and persists this credential before saving it.
            cls._write_api_login(supplied_key)
            cls._set_setting(cls.API_KEY_SETTING, encrypt_value(supplied_key))
        if normalized_mode == cls.MODE_API_KEY and not (supplied_key or cls.api_key()):
            raise ValueError("Add an OpenAI API key before selecting API key authentication")
        cls._set_setting(cls.MODE_SETTING, normalized_mode)
        return cls.settings_payload()


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
        return CodexAuthService.is_authenticated(codex)

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
            if CodexAuthService.profile_status(codex)[0]:
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
                env=CodexAuthService.profile_environment(),
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
            authenticated = return_code == 0 and CodexAuthService.profile_status()[0]
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
            [codex, "logout"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=CodexAuthService.profile_environment(),
        )
        if result.returncode != 0:
            raise RuntimeError("Codex logout failed")
        with cls._lock:
            cls._attempt = None
        return {"authenticated": False, "message": "Codex CLI has been logged out."}
