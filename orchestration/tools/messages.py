from __future__ import annotations

import logging

from orchestration.models import UserMessage
from orchestration.notifications import send_message_push_to_all
from orchestration.registry import register_function
from openai_integration.services import ChatAIService

logger = logging.getLogger(__name__)


@register_function(
    manifest_id="messages.send_message",
    module="messages",
    name="messages.send_message",
    description="Send a standalone inbox message with a push notification.",
    params_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "kind": {"type": "string", "description": "info|call_missed|call_text"},
        },
        "required": ["body"],
    },
)
def send_message(title: str = "", body: str = "", kind: str = "info"):
    phrased_body = ChatAIService.phrase_inbox_message(body, title=title, kind=kind)
    msg = UserMessage.objects.create(title=title, body=phrased_body, kind=kind)
    try:
        send_message_push_to_all(
            title=title or "Corv message",
            body=phrased_body,
            data={"message_id": str(msg.id)},
        )
    except Exception:
        logger.exception("messages.send_message push failed id=%s", msg.id)
    return {"id": str(msg.id)}
