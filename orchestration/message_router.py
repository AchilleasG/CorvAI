from __future__ import annotations

import uuid
from typing import Optional

from orchestration.models import Job
from orchestration.schemas import MessageEnvelope


class MessageRouter:
    """
    Utility to persist MessageEnvelopes into chat history with correct defaults.
    """

    @staticmethod
    def emit(chat_id, envelope: MessageEnvelope, job: Optional[Job] = None):
        if job:
            envelope.job_id = str(job.id)
            envelope.trace_id = envelope.trace_id or job.trace_id
        # Lazy import to avoid circular import at module load time
        from chat.services import ChatService  # pylint: disable=imported-auth,cyclic-import
        return ChatService.add_envelope_to_chat(chat_id, envelope, job=job)

    @staticmethod
    def frontman_update(
        chat_id,
        *,
        content: str,
        job: Optional[Job] = None,
        trace_id: Optional[str] = None,
        message_type: str = "user_visible",
    ):
        envelope = MessageEnvelope(
            trace_id=trace_id or (job.trace_id if job else str(uuid.uuid4())),
            role="frontman",
            type=message_type,
            audience="user",
            content=content,
            job_id=str(job.id) if job else None,
        )
        return MessageRouter.emit(chat_id, envelope, job=job)

    @staticmethod
    def tool_only_note(
        chat_id,
        *,
        content: str,
        role: str,
        job: Optional[Job] = None,
        trace_id: Optional[str] = None,
        call_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        envelope = MessageEnvelope(
            trace_id=trace_id or (job.trace_id if job else str(uuid.uuid4())),
            role=role,
            type="tool_only",
            audience="ai_stack",
            content=content,
            call_id=call_id,
            job_id=str(job.id) if job else None,
            metadata=metadata or {},
        )
        return MessageRouter.emit(chat_id, envelope, job=job)
