import json
import logging
from typing import Optional, Dict, Any, List
import threading

from chat.models import Chat, ChatMessage
from openai_integration.services import ChatAIService
from orchestration.schemas import MessageEnvelope, FunctionCallPayload
from orchestration.services import (
    JobService,
)
from orchestration.message_router import MessageRouter
from orchestration.models import Job
from orchestration.function_caller import FunctionCallOrchestrator

logger = logging.getLogger(__name__)


class ChatService:
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

    @staticmethod
    def construct_chat_context(chat_id: int, limit: int = 20):
        chat = ChatService.get_chat_by_id(chat_id)
        if not chat:
            return None

        # Grab most recent N (index uses chat+created_at), then reverse to oldest→newest
        recent_qs = ChatMessage.objects.filter(chat_id=chat_id).order_by("-created_at")[
            :limit
        ]
        messages = list(reversed(recent_qs))

        return {
            "chat": chat,
            "messages": messages,
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
            return {"success": False, "message": "Chat not found"}
        response = ChatAIService.frontman_decision(chat_context)
        print(f"Frontman decision raw: {response}")
        if not response:
            return {"success": False, "message": "Failed to generate response"}

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
    def handle_user_input(chat_id: int, user_text: str):
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

        message = ChatService.add_message_to_chat(chat_id, user_text, role="user")
        print(f"Message saved: {message}")
        if message is None:
            return {"success": False, "message": "Failed to save message"}
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
                        content="The job failed due to an internal error. Please try again.",
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
                        content="The job failed due to an internal error. Please try again.",
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
