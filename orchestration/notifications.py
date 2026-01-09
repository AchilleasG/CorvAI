from __future__ import annotations

import logging
from typing import Iterable, Optional, Dict, Any

import httpx

from orchestration.models import PushToken

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


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
    tokens = PushToken.objects.values_list("token", flat=True)
    send_push(tokens=tokens, title=title, body=body, data=data)
