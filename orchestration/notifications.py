from __future__ import annotations

import json
import logging
import os
from typing import Iterable, Optional, Dict, Any, Tuple

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from orchestration.models import PushToken

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


def send_push(
    *,
    tokens: Iterable[str],
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    payload = []
    for token in tokens:
        payload.append(
            {
                "to": token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": data or {},
            }
        )
    if not payload:
        return
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(EXPO_PUSH_URL, json=payload)
            resp.raise_for_status()
    except Exception as exc:
        logger.exception("Push notification failed: %s", exc)


def send_push_to_all(*, title: str, body: str, data: Optional[Dict[str, Any]] = None) -> None:
    tokens = PushToken.objects.exclude(platform="android_fcm").values_list("token", flat=True)
    send_push(tokens=tokens, title=title, body=body, data=data)


def _load_fcm_credentials() -> Tuple[Optional[str], Optional[service_account.Credentials]]:
    project_id = os.getenv("FCM_PROJECT_ID")
    raw = os.getenv("FCM_SERVICE_ACCOUNT_JSON")
    path = os.getenv("FCM_SERVICE_ACCOUNT_FILE")
    info = None
    if raw:
        try:
            info = json.loads(raw)
        except Exception:
            logger.exception("Invalid FCM_SERVICE_ACCOUNT_JSON")
            return None, None
    elif path:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                info = json.load(handle)
        except Exception:
            logger.exception("Failed to read FCM_SERVICE_ACCOUNT_FILE")
            return None, None
    if info and not project_id:
        project_id = info.get("project_id")
    if not info or not project_id:
        return None, None
    creds = service_account.Credentials.from_service_account_info(info, scopes=[FCM_SCOPE])
    return project_id, creds


def send_fcm(
    *,
    tokens: Iterable[str],
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    include_notification: bool = True,
) -> None:
    project_id, creds = _load_fcm_credentials()
    if not project_id or not creds:
        logger.warning("FCM credentials missing; skipping FCM send")
        return
    request = Request()
    creds.refresh(request)
    headers = {"Authorization": f"Bearer {creds.token}"}
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    safe_data = {str(k): "" if v is None else str(v) for k, v in (data or {}).items()}
    for token in tokens:
        payload = {
            "message": {
                "token": token,
                "data": safe_data,
                "android": {
                    "priority": "HIGH",
                },
            }
        }
        if include_notification:
            payload["message"]["notification"] = {"title": title, "body": body}
            payload["message"]["android"]["notification"] = {
                "channel_id": "corv_calls",
                "sound": "default",
            }
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.is_error:
                    logger.error("FCM send failed for token %s: %s", token, resp.text)
                    try:
                        data = resp.json()
                        details = (data.get("error") or {}).get("details") or []
                        for item in details:
                            if item.get("errorCode") == "UNREGISTERED":
                                PushToken.objects.filter(token=token).delete()
                                logger.info("FCM token removed as UNREGISTERED: %s", token)
                                break
                    except Exception:
                        logger.exception("Failed parsing FCM error response")
                else:
                    logger.info("FCM send ok for token %s", token)
                resp.raise_for_status()
        except Exception as exc:
            logger.exception("FCM notification failed: %s", exc)


def send_call_push_to_all(*, title: str, body: str, data: Optional[Dict[str, Any]] = None) -> None:
    tokens = list(
        PushToken.objects.filter(platform="android_fcm").values_list("token", flat=True)
    )
    logger.info("FCM call push token_count=%s", len(tokens))
    send_fcm(tokens=tokens, title=title, body=body, data=data, include_notification=False)


def send_message_push_to_all(
    *, title: str, body: str, data: Optional[Dict[str, Any]] = None
) -> None:
    payload = dict(data or {})
    payload.setdefault("type", "user_message")
    payload.setdefault("title", title)
    payload.setdefault("body", body)
    expo_tokens = PushToken.objects.filter(
        platform__in=["ios", "web", "unknown"]
    ).values_list("token", flat=True)
    send_push(tokens=expo_tokens, title=title, body=body, data=payload)
    tokens = list(
        PushToken.objects.filter(platform="android_fcm").values_list("token", flat=True)
    )
    if not tokens:
        return
    logger.info("FCM message push token_count=%s", len(tokens))
    send_fcm(tokens=tokens, title=title, body=body, data=payload, include_notification=True)
