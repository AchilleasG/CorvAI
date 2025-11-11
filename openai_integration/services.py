# services/chat_ai.py
from __future__ import annotations

from typing import Dict, Any, List, Sequence, Union
from django.db import transaction
from openai import OpenAI

from chat.models import ChatMessage  # adjust if your app label differs
from Corv.config import settings     # your Pydantic Settings (with openai_key)
from openai_integration.personality import (
    build_personality_system_message,
    build_user_profile_message,
)


class ChatAIService:
    """
    LLM reply generator backed by OpenAI Responses API.
    All methods are static for easy import & testing.
    """

    # Map your DB roles to OpenAI Responses roles
    ROLE_MAP = {
        "user": "user",
        "assistant": "assistant",
        "system": "developer",  # map system->developer for steerability
        "tool": "tool",
    }

    # Single shared client (initialized at import)
    client = OpenAI(api_key=settings.openai_key)

    @staticmethod
    
    def _messages_to_openai_input(messages: Sequence[Union[ChatMessage, Dict[str, str]]]):
        out = []
        for m in messages:
            if isinstance(m, dict):
                raw_role = m.get("role", "user")
                text_value = m.get("text", "")
            else:
                raw_role = getattr(m, "role", "user")
                text_value = getattr(m, "text", "")

            role = ChatAIService.ROLE_MAP.get(raw_role, "user")
            # Assistant turns must be output_text; everything else you send in is input_text.
            content_type = "output_text" if role == "assistant" else "input_text"
            out.append({
                "role": role,
                "content": [{"type": content_type, "text": text_value}],
            })
        return out

    @staticmethod
    @transaction.atomic
    def generate_reply_from_context(
        context: Dict[str, Any],
        model: str = "gpt-5",
    ) -> ChatMessage:
        """
        Given the dict returned by `construct_chat_context`, generate the next assistant
        message using the OpenAI Responses API and persist it as a ChatMessage.

        Returns the created ChatMessage instance.
        """
        if not context or "chat" not in context or "messages" not in context:
            raise ValueError("Invalid context: expected keys 'chat' and 'messages'.")

        history: List[ChatMessage] = context["messages"]
        dynamic_context: List[Dict[str, str]] = context.get("dynamic_context", [])
        user_profile_id = context.get("user_profile_id")
        system_message = {
            "role": "system",
            "text": build_personality_system_message(),
        }
        user_profile_message = build_user_profile_message(user_profile_id)
        profile_messages = (
            [{"role": "system", "text": user_profile_message}]
            if user_profile_message
            else []
        )

        combined_context = [system_message, *profile_messages, *dynamic_context, *history]
        input_seq = ChatAIService._messages_to_openai_input(combined_context)
        print(f"Input sequence for OpenAI: {input_seq}")
        resp = ChatAIService.client.responses.create(
            model=model,
            input=input_seq,
            text={"format": {"type": "text"}, "verbosity": "medium"},
            reasoning={"effort": "minimal"},
            tools=[],    # add tool specs here if/when you support tool calls
            store=True,  # optional
        )

        # Preferred accessor for plain text (newer SDKs)
        assistant_text = getattr(resp, "output_text", None)
        return assistant_text

    @staticmethod
    def transcribe_audio(
        audio_file_path: str,
        model: str = "whisper-1",
    ) -> str:
        """
        Transcribe the given audio file using OpenAI's Whisper model.
        Returns the transcribed text.
        """
        with open(audio_file_path, "rb") as audio_file:
            transcription = ChatAIService.client.audio.transcriptions.create(
                model=model, 
                file=audio_file,
                response_format="text"
            )
        return transcription if transcription else ""
