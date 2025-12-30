# services/chat_ai.py
from __future__ import annotations

from typing import Dict, Any, List
from django.db import transaction
from openai import OpenAI

from chat.models import ChatMessage  # adjust if your app label differs
from Corv.config import settings     # your Pydantic Settings (with openai_key)
from orchestration.services import ModuleDirectory, PersonaService


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
    
    def _messages_to_openai_input(messages, *, lead_developer_text: str = ""):
        out = []
        if lead_developer_text:
            out.append(
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": lead_developer_text}],
                }
            )
        for m in messages:
            role = ChatAIService.ROLE_MAP.get(m.role, "user")
            # Assistant turns must be output_text; everything else you send in is input_text.
            content_type = "output_text" if role == "assistant" else "input_text"
            ts = ""
            if getattr(m, "created_at", None):
                ts = f"[{m.created_at.isoformat()}] "
            out.append({
                "role": role,
                "content": [{"type": content_type, "text": f"{ts}{m.text}"}],
            })
        return out

    @staticmethod
    @transaction.atomic
    def generate_reply_from_context(
        context: Dict[str, Any],
        model: str = "gpt-5.2",
    ) -> ChatMessage:
        """
        Given the dict returned by `construct_chat_context`, generate the next assistant
        message using the OpenAI Responses API and persist it as a ChatMessage.

        Returns the created ChatMessage instance.
        """
        if not context or "chat" not in context or "messages" not in context:
            raise ValueError("Invalid context: expected keys 'chat' and 'messages'.")

        history: List[ChatMessage] = context["messages"]

        # Build developer prompt with persona + module inventory
        persona_text = PersonaService.build_persona_prompt()
        module_lines = ModuleDirectory.module_summaries()
        module_text = "\n".join(
            f"- {m['name']} ({m['slug']}): {m['description']} [{m['function_count']} functions]"
            for m in module_lines
        )
        lead_text = persona_text
        if module_text:
            lead_text = f"{persona_text}\n\nAvailable modules:\n{module_text}"

        input_seq = ChatAIService._messages_to_openai_input(history, lead_developer_text=lead_text)

        print(f"Input sequence for OpenAI: {input_seq}")
        resp = ChatAIService.client.responses.create(
            model=model,
            input=input_seq,
            text={"format": {"type": "text"}, "verbosity": "medium"},
            reasoning={"effort": "low"},
            tools=ModuleDirectory.function_tool_specs(),    # centrally expose tools
            store=True,  # optional
        )

        # Preferred accessor for plain text (newer SDKs)
        assistant_text = getattr(resp, "output_text", None)
        return assistant_text

    @staticmethod
    def frontman_decision(
        context: Dict[str, Any],
        model: str = "gpt-5.2",
    ) -> str:
        """
        First-pass call: Front Man either responds normally or signals a handoff.
        Output is raw text; caller is responsible for parsing the handoff JSON.
        """
        if not context or "chat" not in context or "messages" not in context:
            raise ValueError("Invalid context: expected keys 'chat' and 'messages'.")

        history: List[ChatMessage] = context["messages"]

        persona_text = PersonaService.build_persona_prompt()
        module_lines = ModuleDirectory.module_summaries()
        module_text = "\n".join(
            f"- {m['name']} ({m['slug']}): {m['description']} [{m['function_count']} functions]"
            for m in module_lines
        )

        instructions = (
            f"{persona_text}\n\n"
            "Decision rule: If the user only needs conversation, reply directly. "
            "If action/data is needed, do NOT answer; instead emit a JSON handoff object.\n"
            "Handoff JSON shape:\n"
            '{\"handoff\":true,\"reason\":\"why\",\"module_hint\":\"optional\"}\n'
            "If not handing off, return {\"handoff\":false,\"reply\":\"your message\"}.\n"
            "Keep JSON terse. No extra prose outside the JSON."
        )

        if module_text:
            instructions += f"\nAvailable modules:\n{module_text}"

        input_seq = ChatAIService._messages_to_openai_input(history, lead_developer_text=instructions)
        resp = ChatAIService.client.responses.create(
            model=model,
            input=input_seq,
            text={"format": {"type": "text"}, "verbosity": "medium"},
            reasoning={"effort": "low"},
            tools=[],    # no tools in first pass; decision only
            store=True,
        )

        assistant_text = getattr(resp, "output_text", None)
        return assistant_text or ""

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
