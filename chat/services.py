import logging
from typing import Dict, List, Optional, Sequence, Union

from chat.models import Chat, ChatMessage
from openai_integration.services import ChatAIService
from mcp.models import MCPModule
from mcp.services import TaskManagerOutcome, TaskManagerService


DynamicContextInput = Union[str, Dict[str, str]]

logger = logging.getLogger(__name__)


class ChatService:
    DEFAULT_USER_TAG = ["text-message"]
    DEFAULT_ASSISTANT_TAG = ["text-message"]
    ACTION_TAG = "action-string"
    ACTION_RESPONSE_TAG = "action-response"

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
        return ChatMessage.objects.filter(chat_id=chat_id).order_by('created_at')

    @staticmethod
    def construct_chat_context(
        chat_id: int,
        limit: int = 20,
        dynamic_context: Union[DynamicContextInput, Sequence[DynamicContextInput], None] = None,
        user_profile_id: str | None = None,
    ):
        """
        Build the payload handed to the LLM layer.
        `dynamic_context` can be a string, dict, or iterable of either, and is prepended
        ahead of the stored chat history.
        """
        chat = ChatService.get_chat_by_id(chat_id)
        if not chat:
            return None

        normalized_context = ChatService._normalize_dynamic_context(dynamic_context)
        module_context = ChatService._build_module_overview()
        if module_context:
            normalized_context = [{"role": "system", "text": module_context}, *normalized_context]

        # Grab most recent N (index uses chat+created_at), then reverse to oldest→newest
        recent_qs = ChatMessage.objects.filter(chat_id=chat_id).order_by("-created_at")[:limit]
        messages = list(reversed(recent_qs))

        return {
            "chat": chat,
            "messages": messages,
            "dynamic_context": normalized_context,
            "user_profile_id": user_profile_id,
        }

    @staticmethod
    def add_message_to_chat(
        chat_id: int,
        text: str,
        role: str = "user",
        tags: Optional[List[str]] = None,
    ):
        chat = ChatService.get_chat_by_id(chat_id)
        if not chat:
            return None
        
        message = ChatMessage(chat=chat, text=text, role=role, tags=tags or [])
        message.save()
        return message

    @staticmethod
    def get_chat_next_message(
        chat_id: int,
        dynamic_context: Union[DynamicContextInput, Sequence[DynamicContextInput], None] = None,
        user_profile_id: str | None = None,
    ):
        chat_context = ChatService.construct_chat_context(
            chat_id,
            dynamic_context=dynamic_context,
            user_profile_id=user_profile_id,
        )
        print(f"Chat context for chat {chat_id}: {chat_context}")
        if not chat_context:
            return {"success": False, "message": "Chat not found"}
        response = ChatAIService.generate_reply_from_context(chat_context)
        print(f"Generated response: {response}")
        if not response:
            return {"success": False, "message": "Failed to generate response"}
        return response

    @staticmethod
    def handle_user_input(
        chat_id: int,
        user_text: str,
        dynamic_context: Union[DynamicContextInput, Sequence[DynamicContextInput], None] = None,
        user_profile_id: str | None = None,
    ):
        print(f"Handling user input for chat {chat_id}: {user_text}")
        chat = ChatService.get_or_create_chat(chat_id)
        chat_id = chat.id
        print(f"Chat {chat_id} exists or created.")
        message = ChatService.add_message_to_chat(
            chat_id,
            user_text,
            role="user",
            tags=ChatService.DEFAULT_USER_TAG,
        )
        print(f"Message saved: {message}")
        if message is None:
            return {"success": False, "message": "Failed to save message"}

        chat_instance = ChatService.get_chat_by_id(chat_id)

        if chat_instance and TaskManagerService.has_pending_plan(chat_instance):
            outcome = ChatService._trigger_task_manager(chat_instance)
            return ChatService._handle_task_outcome(chat_id, outcome, user_profile_id)

        response = ChatService.get_chat_next_message(
            chat_id,
            dynamic_context=dynamic_context,
            user_profile_id=user_profile_id,
        )
        print(f"Response from chat service: {response}")
        tags = ChatService._assistant_tags(response)
        ChatService.add_message_to_chat(chat_id, response, role="assistant", tags=tags)

        if ChatService.ACTION_TAG in tags and chat_instance:
            outcome = ChatService._trigger_task_manager(chat_instance)
            return ChatService._handle_task_outcome(chat_id, outcome, user_profile_id)

        return {"success": True, "message": response, "chat_id": str(chat_id)}

    @staticmethod
    def _normalize_dynamic_context(
        dynamic_context: Union[DynamicContextInput, Sequence[DynamicContextInput], None]
    ) -> List[Dict[str, str]]:
        if dynamic_context is None:
            return []

        if isinstance(dynamic_context, (str, dict)):
            items: Sequence[DynamicContextInput] = [dynamic_context]
        else:
            items = dynamic_context

        normalized: List[Dict[str, str]] = []
        for raw in items:
            if isinstance(raw, str):
                text = raw.strip()
                if not text:
                    continue
                normalized.append({"role": "system", "text": text})
                continue

            if isinstance(raw, dict):
                text = (raw.get("text") or "").strip()
                if not text:
                    continue
                role = (raw.get("role") or "system").strip() or "system"
                normalized.append({"role": role, "text": text})
                continue

            raise ValueError("Dynamic context entries must be strings or dicts.")

        return normalized

    @staticmethod
    def _assistant_tags(response_text: str) -> List[str]:
        if ChatService._is_action_trigger(response_text):
            return [ChatService.ACTION_TAG]
        return ChatService.DEFAULT_ASSISTANT_TAG

    @staticmethod
    def _is_action_trigger(response_text: str) -> bool:
        if not isinstance(response_text, str):
            return False
        return response_text.strip().lower() == TaskManagerService.ACTION_TRIGGER

    @staticmethod
    def _trigger_task_manager(chat: Chat) -> TaskManagerOutcome:
        try:
            return TaskManagerService.process_chat(chat)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Task manager orchestration failed",
                extra={"chat_id": str(chat.id)},
            )
            return TaskManagerOutcome(
                status="error",
                frontman_context="I hit a snag while coordinating tasks. Let the user know something went wrong and that you're on it.",
                error=str(exc),
            )

    @staticmethod
    def _handle_task_outcome(
        chat_id: int,
        outcome: TaskManagerOutcome,
        user_profile_id: Optional[str],
    ):
        if not outcome:
            return {"success": True, "message": "", "chat_id": str(chat_id)}

        if outcome.frontman_context:
            guided_response = ChatService._render_action_response(
                chat_id,
                outcome.frontman_context,
                user_profile_id=user_profile_id,
            )
            ChatService.add_message_to_chat(
                chat_id,
                guided_response,
                role="assistant",
                tags=[ChatService.ACTION_RESPONSE_TAG, *ChatService.DEFAULT_ASSISTANT_TAG],
            )
            return {"success": True, "message": guided_response, "chat_id": str(chat_id)}

        if outcome.status == "error":
            fallback = "Something went wrong handling that action. Please try again later."
            ChatService.add_message_to_chat(
                chat_id,
                fallback,
                role="assistant",
                tags=[ChatService.ACTION_RESPONSE_TAG, *ChatService.DEFAULT_ASSISTANT_TAG],
            )
            return {"success": False, "message": fallback, "chat_id": str(chat_id)}

        return {"success": True, "message": "", "chat_id": str(chat_id)}

    @staticmethod
    def _render_action_response(
        chat_id: int,
        instructions: str,
        user_profile_id: Optional[str],
    ) -> str:
        contextual_prompt = [
            {
                "role": "system",
                "text": instructions,
            }
        ]
        response = ChatService.get_chat_next_message(
            chat_id,
            dynamic_context=contextual_prompt,
            user_profile_id=user_profile_id,
        )
        return response if isinstance(response, str) else str(response)

    @staticmethod
    def _build_module_overview() -> str:
        modules = list(MCPModule.objects.order_by("name").values("name", "description"))
        if not modules:
            return ""

        lines = [
            "Capabilities overview (reference only—Task Manager handles the how):"
        ]
        for module in modules:
            description = module.get("description") or ""
            lines.append(f"- {module['name']}: {description}")
        lines.extend(
            [
                "",
                "Execution protocol:",
                "- You are the front-line assistant. Never describe step-by-step execution.",
                "- If a request requires any module/tool call, reply with exactly the text 'action-prompt' so the Task Manager AI can take over.",
                "- Once the Task Manager reports back, summarize the results conversationally.",
            ]
        )
        return "\n".join(lines)
