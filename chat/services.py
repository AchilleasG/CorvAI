import json
import logging
from typing import Optional, Dict, Any, List
import copy
import re
import threading

from chat.models import Chat, ChatMessage
from openai_integration.services import ChatAIService
from orchestration.schemas import MessageEnvelope, FunctionCallPayload
from orchestration.services import (
    JobService,
    ModelConfigService,
)
from orchestration.message_router import MessageRouter
from orchestration.models import Job
from orchestration.function_caller import FunctionCallOrchestrator

logger = logging.getLogger(__name__)


class ChatService:
    _UPSTREAM_FAILURE_REPLY = (
        "I'm having trouble reaching the model service right now. Please try again in a moment."
    )
    _PROVIDER_QUOTA_REPLY = (
        "Corv couldn't respond because the configured AI provider account has no API credits "
        "remaining. Add credits or update the API key, then try again."
    )
    _PROVIDER_RATE_LIMIT_REPLY = (
        "The AI provider is temporarily rate-limiting Corv. Please wait a moment and try again."
    )
    _PROVIDER_AUTH_REPLY = (
        "Corv couldn't authenticate with the configured AI provider. Check the API key and "
        "provider settings, then try again."
    )

    @staticmethod
    def get_chat_by_id(chat_id: int):
        try:
            return Chat.objects.get(id=chat_id)
        except Chat.DoesNotExist:
            return None

    @staticmethod
    def get_or_create_chat(chat_id: int):
        chat = ChatService.get_chat_by_id(chat_id)
        if not chat:
            chat = Chat.objects.create()
        return chat

    @staticmethod
    def get_chat_messages(chat_id: int):
        return ChatMessage.objects.filter(chat_id=chat_id).order_by("created_at")

    CONTEXT_SUMMARY_KEY = "rolling_context_summary"

    @staticmethod
    def _set_initial_chat_title(chat, user_text: str) -> None:
        """Title an unnamed chat from its first user message without blocking chat on errors."""
        if (chat.nickname or "").strip():
            return
        first_user_message = (
            ChatMessage.objects.filter(chat=chat, role="user")
            .order_by("created_at", "id")
            .first()
        )
        if not first_user_message or first_user_message.text != user_text:
            return
        try:
            generated = ChatAIService.generate_chat_title(user_text)
        except Exception:
            logger.exception("Could not generate title for chat %s", chat.id)
            return
        title = re.sub(r"\s+", " ", generated or "").strip().strip("\"'` ")
        title = re.sub(r"^title\s*:\s*", "", title, flags=re.IGNORECASE).strip()
        title = title.rstrip(".!?:;,- ")[:80].strip()
        if title:
            from django.db.models import Q

            Chat.objects.filter(Q(nickname__isnull=True) | Q(nickname=""), id=chat.id).update(
                nickname=title
            )

    @staticmethod
    def _estimate_context_tokens(message) -> int:
        # A conservative dependency-free estimate that handles non-ASCII text too.
        text = getattr(message, "text", "") or ""
        return max(1, (len(text.encode("utf-8")) + 3) // 4) + 16

    @staticmethod
    def _truncate_context_message(message, token_budget: int):
        """Return an in-memory copy when a single stored message exceeds the budget."""
        cloned = copy.copy(message)
        max_bytes = max(256, (token_budget - 20) * 4)
        raw = (message.text or "").encode("utf-8")
        if len(raw) <= max_bytes:
            return cloned
        half = max_bytes // 2
        start = raw[:half].decode("utf-8", errors="ignore")
        end = raw[-half:].decode("utf-8", errors="ignore")
        cloned.text = f"{start}\n\n[Older content clipped to fit context]\n\n{end}"
        return cloned

    @staticmethod
    def _refresh_context_summary(chat, summary, dropped):
        if not dropped:
            return summary
        metadata = summary.metadata if summary and isinstance(summary.metadata, dict) else {}
        cutoff = str(metadata.get("summarized_through_id", ""))
        new_messages = []
        seen_cutoff = not cutoff
        for message in dropped:
            if seen_cutoff:
                new_messages.append(message)
            elif str(message.id) == cutoff:
                seen_cutoff = True
        # If the cutoff is newer than the dropped boundary, everything here is already
        # represented. This is the normal case while the recent window rotates slowly.
        if cutoff and not seen_cutoff:
            return summary
        if not new_messages:
            return summary
        try:
            # Bound each compaction request. This also upgrades very long pre-existing
            # chats safely instead of sending their entire archive in one model call.
            batches = []
            batch = []
            batch_tokens = 0
            for message in new_messages:
                message_tokens = ChatService._estimate_context_tokens(message)
                if batch and batch_tokens + message_tokens > 100000:
                    batches.append(batch)
                    batch = []
                    batch_tokens = 0
                batch.append(message)
                batch_tokens += message_tokens
            if batch:
                batches.append(batch)

            replacement = summary.text if summary else ""
            for message_batch in batches:
                replacement = ChatAIService.summarize_chat_history(
                    replacement,
                    message_batch,
                    max_output_tokens=ModelConfigService.get_chat_summary_tokens(),
                )
                if not replacement:
                    return summary
        except Exception:
            logger.exception("Could not refresh rolling context summary for chat %s", chat.id)
            return summary
        summary_metadata = {
            ChatService.CONTEXT_SUMMARY_KEY: True,
            "summarized_through_id": str(dropped[-1].id),
            "summarized_message_count": int(metadata.get("summarized_message_count", 0)) + len(new_messages),
        }
        if summary:
            summary.text = replacement
            summary.metadata = summary_metadata
            summary.save(update_fields=["text", "metadata"])
            return summary
        return ChatMessage.objects.create(
            chat=chat,
            text=replacement,
            role="system",
            message_type="system_note",
            audience="ai_stack",
            metadata=summary_metadata,
        )

    @staticmethod
    def construct_chat_context(chat_id: int, token_budget: int | None = None):
        """Build a recent, token-budgeted window plus durable long-term memory."""
        chat = ChatService.get_chat_by_id(chat_id)
        if not chat:
            return None

        budget = token_budget or ModelConfigService.get_chat_context_tokens()
        budget = max(int(budget), 128)
        summary = ChatMessage.objects.filter(
            chat_id=chat_id,
            metadata__rolling_context_summary=True,
        ).order_by("-created_at").first()
        messages = []
        for message in ChatMessage.objects.filter(chat_id=chat_id).order_by("created_at", "id"):
            metadata = message.metadata if isinstance(message.metadata, dict) else {}
            if metadata.get(ChatService.CONTEXT_SUMMARY_KEY):
                continue
            if message.message_type == "tool_only" and not (
                message.audience == "ai_stack" and metadata.get("include_in_context") is True
            ):
                continue
            file_ids = metadata.get("attachment_file_ids", [])
            if file_ids and message.role == "user":
                try:
                    from coding.files import attachment_context
                    attachment_text = attachment_context(file_ids)
                    if attachment_text:
                        message = copy.copy(message)
                        message.text = f"{message.text}\n\n{attachment_text}"
                except Exception:
                    logger.exception("Could not add attachments to chat context")
            messages.append(message)

        summary_tokens = ChatService._estimate_context_tokens(summary) if summary else 0
        available = max(64, budget - summary_tokens)
        selected_reversed = []
        used = 0
        for message in reversed(messages):
            message_tokens = ChatService._estimate_context_tokens(message)
            if selected_reversed and used + message_tokens > available:
                break
            if not selected_reversed and message_tokens > available:
                message = ChatService._truncate_context_message(message, available)
                message_tokens = ChatService._estimate_context_tokens(message)
            selected_reversed.append(message)
            used += message_tokens
        selected = list(reversed(selected_reversed))
        dropped = messages[: len(messages) - len(selected)]

        summary = ChatService._refresh_context_summary(chat, summary, dropped)
        context_messages = ([summary] if summary else []) + selected
        return {
            "chat": chat,
            "messages": context_messages,
            "context_meta": {
                "token_budget": budget,
                "estimated_tokens": sum(ChatService._estimate_context_tokens(m) for m in context_messages),
                "summarized_messages": len(dropped),
            },
        }

    @staticmethod
    def add_message_to_chat(
        chat_id: int,
        text: str,
        role: str = "user",
        message_type: str = "user_visible",
        audience: str = "user",
        trace_id: str = "",
        call_id: str = "",
        job=None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        chat = ChatService.get_chat_by_id(chat_id)
        if not chat:
            return None

        message = ChatMessage(
            chat=chat,
            text=text,
            role=role,
            message_type=message_type,
            audience=audience,
            trace_id=trace_id,
            call_id=call_id,
            job=job,
            metadata=metadata or {},
        )
        message.save()
        if role == "assistant" and job:
            from coding.models import ManagedFile

            job.refresh_from_db(fields=["metadata"])
            job_metadata = job.metadata if isinstance(job.metadata, dict) else {}
            pending_sources = [item for item in job_metadata.get("pending_sources", []) if isinstance(item, dict)]
            if pending_sources:
                message.metadata = {**message.metadata, "sources": pending_sources[:12]}
                message.save(update_fields=["metadata"])
                job_metadata.pop("pending_sources", None)
                job.metadata = job_metadata
                job.save(update_fields=["metadata", "updated_at"])
            pending_ids = [str(value) for value in job_metadata.get("pending_file_ids", [])]
            if pending_ids:
                files = list(ManagedFile.objects.filter(id__in=pending_ids))
                attachments = []
                for item in files:
                    item.assistant_message = message
                    item.save(update_fields=["assistant_message", "updated_at"])
                    attachments.append({
                        "id": str(item.id), "filename": item.filename,
                        "content_type": item.content_type, "size": item.size,
                        "checksum_sha256": item.checksum_sha256,
                        "metadata": item.metadata, "tags": item.tags,
                        "session_id": str(item.session_id) if item.session_id else None,
                        "turn_id": str(item.turn_id) if item.turn_id else None,
                        "assistant_message_id": str(message.id),
                        "download_url": f"/api/files/{item.id}/content",
                        "created_at": item.created_at.isoformat(),
                        "updated_at": item.updated_at.isoformat(),
                    })
                if attachments:
                    message.metadata = {**message.metadata, "attachments": attachments}
                    message.save(update_fields=["metadata"])
                job_metadata.pop("pending_file_ids", None)
                job.metadata = job_metadata
                job.save(update_fields=["metadata", "updated_at"])
        return message

    @staticmethod
    def add_envelope_to_chat(chat_id: int, envelope: MessageEnvelope, job=None):
        """
        Persist a MessageEnvelope into ChatMessage storage so the AI stack has full context.
        """
        return ChatService.add_message_to_chat(
            chat_id=chat_id,
            text=envelope.content,
            role=envelope.role if envelope.role != "frontman" else "assistant",
            message_type=envelope.type,
            audience=envelope.audience,
            trace_id=envelope.trace_id,
            call_id=envelope.call_id or "",
            job=job,
            metadata=envelope.metadata,
        )

    @staticmethod
    def get_chat_next_message(chat_id: int):
        chat_context = ChatService.construct_chat_context(chat_id)
        print(f"Chat context for chat {chat_id}: {chat_context}")
        if not chat_context:
            return "I couldn't find that chat. Please refresh and try again."

        try:
            response = ChatAIService.frontman_decision(chat_context)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Frontman decision failed for chat %s", chat_id)
            return ChatService._safe_assistant_reply(exc)

        print(f"Frontman decision raw: {response}")
        if not response:
            return ChatService._UPSTREAM_FAILURE_REPLY

        if ChatService._looks_like_upstream_html_error(response):
            logger.warning("Blocked upstream HTML error payload in chat %s", chat_id)
            return ChatService._UPSTREAM_FAILURE_REPLY

        decision = ChatService._parse_decision(response)
        if not decision:
            # Fallback: treat as plain assistant reply
            return response

        if not decision.get("handoff"):
            return decision.get("reply", "")

        # Handoff path: create a job and run calls via Function Caller
        module_hint = decision.get("module_hint")
        job = JobService.create_job(
            chat=chat_context["chat"],
            session_id="",
            trace_id="",
            module=None,
            user_visible_summary=decision.get("reason", "Running requested action"),
        )
        JobService.mark_status(job, Job.STATUS_RUNNING)

        MessageRouter.frontman_update(
            chat_id=chat_context["chat"].id,
            content="Got it. I'll run this and report back.",
            job=job,
            message_type="user_visible",
        )

        # Run the caller in a background thread so the ack is delivered immediately.
        threading.Thread(
            target=ChatService._run_job_async,
            args=(chat_context["chat"].id, job.id),
            daemon=True,
        ).start()
        return "Got it. I'll run this and report back."

    @staticmethod
    def handle_user_input(chat_id: int, user_text: str, metadata=None):
        print(f"Handling user input for chat {chat_id}: {user_text}")
        chat = ChatService.get_or_create_chat(chat_id)
        chat_id = chat.id
        print(f"Chat {chat_id} exists or created.")
        # Before logging, check for a waiting job to resume
        from orchestration.models import Job  # local import to avoid circulars

        waiting_job = (
            Job.objects.filter(chat_id=chat_id, status=Job.STATUS_WAITING_USER)
            .order_by("-created_at")
            .first()
        )

        message = ChatService.add_message_to_chat(chat_id, user_text, role="user", metadata=metadata or {})
        print(f"Message saved: {message}")
        if message is None:
            return {"success": False, "message": "Failed to save message"}
        ChatService._set_initial_chat_title(chat, user_text)
        if waiting_job:
            # Resume the pending job with the new user input
            waiting_job.refresh_from_db()
            waiting_job.status = Job.STATUS_RUNNING
            waiting_job.save(update_fields=["status", "updated_at"])
            chat_context = ChatService.construct_chat_context(chat_id)
            threading.Thread(
                target=ChatService._run_resume_async,
                args=(chat_context, waiting_job.id, user_text),
                daemon=True,
            ).start()
            return {
                "success": True,
                "message": "Got it. Continuing and will report back.",
                "chat_id": str(chat_id),
            }

        response = ChatService.get_chat_next_message(chat_id)
        print(f"Response from chat service: {response}")
        # Avoid duplicating identical consecutive assistant messages
        last_assistant = (
            ChatMessage.objects.filter(chat_id=chat_id, role="assistant")
            .order_by("-created_at")
            .first()
        )
        if not last_assistant or last_assistant.text != response:
            ChatService.add_message_to_chat(chat_id, response, role="assistant")
        return {"success": True, "message": response, "chat_id": str(chat_id)}

    @staticmethod
    def _safe_assistant_reply(exc: Exception) -> str:
        msg = str(exc)
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error = body.get("error", body)
            if isinstance(error, dict):
                provider_code = str(error.get("code") or "").lower()
                provider_type = str(error.get("type") or "").lower()
                provider_message = str(error.get("message") or "")
                msg = " ".join((msg, provider_code, provider_type, provider_message))

        probe = msg.lower()
        quota_markers = (
            "insufficient_quota",
            "credit_balance_exhausted",
            "no credits remaining",
            "quota exceeded",
            "billing hard limit",
        )
        if any(marker in probe for marker in quota_markers):
            return ChatService._PROVIDER_QUOTA_REPLY

        status_code = getattr(exc, "status_code", None)
        if status_code == 429 or "rate limit" in probe or "too many requests" in probe:
            return ChatService._PROVIDER_RATE_LIMIT_REPLY
        if status_code in (401, 403) or any(
            marker in probe
            for marker in ("invalid api key", "incorrect api key", "authentication error")
        ):
            return ChatService._PROVIDER_AUTH_REPLY
        if ChatService._looks_like_upstream_html_error(msg):
            return ChatService._UPSTREAM_FAILURE_REPLY
        return "I ran into a temporary internal error. Please try again."

    @staticmethod
    def _looks_like_upstream_html_error(text: str) -> bool:
        if not text:
            return False
        probe = text.strip().lower()
        if "<html" in probe or "<!doctype html" in probe:
            return True
        markers = (
            "cloudflare",
            "bad gateway",
            "error code: 502",
            "502 bad gateway",
            "origin server",
        )
        return any(marker in probe for marker in markers)

    @staticmethod
    def _run_job_async(chat_id: int, job_id):
        """
        Execute Function Caller in background and log the result.
        """
        try:
            from orchestration.models import Job as JobModel

            job = JobModel.objects.get(id=job_id)
            chat_context = ChatService.construct_chat_context(chat_id)
            summary_text = FunctionCallOrchestrator.run(chat_context, job)
            JobService.mark_status(job, Job.STATUS_COMPLETED)
            ChatService.add_message_to_chat(
                chat_id, summary_text, role="assistant", job=job
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Background job crashed")
            try:
                from orchestration.models import Job as JobModel

                job = JobModel.objects.filter(id=job_id).first()
                if job:
                    JobService.mark_status(
                        job, Job.STATUS_FAILED, error_summary=str(exc)
                    )
                    MessageRouter.tool_only_note(
                        chat_id=chat_id,
                        content=f"Function Caller crash: {exc}",
                        role="caller",
                        job=job,
                    )
                    MessageRouter.frontman_update(
                        chat_id=chat_id,
                        content=ChatService._safe_assistant_reply(exc),
                        job=job,
                        message_type="user_visible",
                    )
                else:
                    ChatService.add_message_to_chat(
                        chat_id,
                        f"Job error: {exc}",
                        role="assistant",
                        job=None,
                    )
            except Exception:
                logger.exception("Failed to record crash for job %s", job_id)

    @staticmethod
    def _run_resume_async(chat_context: Dict[str, Any], job_id, user_response: str):
        try:
            from orchestration.models import Job as JobModel

            job = JobModel.objects.get(id=job_id)
            summary_text = FunctionCallOrchestrator.resume(
                chat_context, job, user_response
            )
            job.refresh_from_db()
            if job.status != Job.STATUS_WAITING_USER:
                JobService.mark_status(job, Job.STATUS_COMPLETED)
            ChatService.add_message_to_chat(
                chat_context["chat"].id, summary_text, role="assistant", job=job
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Resume job crashed")
            try:
                from orchestration.models import Job as JobModel

                job = JobModel.objects.filter(id=job_id).first()
                if job:
                    JobService.mark_status(
                        job, Job.STATUS_FAILED, error_summary=str(exc)
                    )
                    MessageRouter.tool_only_note(
                        chat_id=chat_context["chat"].id,
                        content=f"Function Caller resume crash: {exc}",
                        role="caller",
                        job=job,
                    )
                    MessageRouter.frontman_update(
                        chat_id=chat_context["chat"].id,
                        content=ChatService._safe_assistant_reply(exc),
                        job=job,
                        message_type="user_visible",
                    )
                else:
                    ChatService.add_message_to_chat(
                        chat_context["chat"].id,
                        f"Job error: {exc}",
                        role="assistant",
                        job=None,
                    )
            except Exception:
                logger.exception("Failed to record crash for resume job %s", job_id)

    @staticmethod
    def _parse_decision(raw: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
