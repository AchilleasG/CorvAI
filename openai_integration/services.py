# services/chat_ai.py
from __future__ import annotations

from typing import Dict, Any, List
import hashlib
import logging
import json
from django.db import transaction

from Corv.config import settings
from chat.models import ChatMessage  # adjust if your app label differs
from orchestration.model_providers import resolve_provider, get_client
from orchestration.services import ModuleDirectory, PersonaService, ModelConfigService, UsageService

logger = logging.getLogger(__name__)


class ChatAIService:
    """
    LLM reply generator that routes to provider-specific clients (OpenAI Responses or X.ai Grok chat completions).
    All methods are static for easy import & testing.
    """

    # Map your DB roles to OpenAI Responses roles
    ROLE_MAP = {
        "user": "user",
        "assistant": "assistant",
        "system": "developer",  # map system->developer for steerability
        "tool": "tool",
    }

    @staticmethod
    def _messages_to_chat_messages(messages, *, system_text: str = ""):
        out = []
        if system_text:
            out.append({"role": "system", "content": system_text})
        for m in messages:
            role = ChatAIService.ROLE_MAP.get(m.role, "user")
            # Chat completions expect "system" instead of "developer".
            if role == "developer":
                role = "system"
            ts = ""
            if getattr(m, "created_at", None):
                ts = f"[{m.created_at.isoformat()}] "
            out.append({"role": role, "content": f"{ts}{m.text}"})
        return out

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
        model: str | None = None,
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

        model_name = model or ModelConfigService.get_frontman_model()
        cache_mode = ModelConfigService.get_cache_mode()
        provider = resolve_provider(model_name)
        usage_obj = None
        prompt_cache_key = ""

        if provider == "openai":
            resp_kwargs = {
                "model": model_name,
                "input": input_seq,
                "text": {"format": {"type": "text"}, "verbosity": "medium"},
                "reasoning": {"effort": "low"},
                "tools": ModuleDirectory.function_tool_specs(),
                "store": True,
            }
            if cache_mode in ("frontman", "all"):
                persona_key = getattr(PersonaService.get_persona(), "slug", "default") or "default"
                module_key = "-".join(sorted(m["slug"] for m in module_lines)) if module_lines else "none"
                key_hash = hashlib.md5(f"{persona_key}|{module_key}".encode("utf-8")).hexdigest()
                prompt_cache_key = f"fmv1-{key_hash}"
                resp_kwargs["prompt_cache_key"] = prompt_cache_key
            resp = get_client("openai").responses.create(**resp_kwargs)
            assistant_text = getattr(resp, "output_text", None)
            usage_obj = getattr(resp, "usage", None)
            try:
                raw = (
                    resp.model_dump()
                    if hasattr(resp, "model_dump")
                    else resp.to_dict()
                    if hasattr(resp, "to_dict")
                    else str(resp)
                )
                logger.warning("Frontman generate response (%s): %s", provider, raw)
            except Exception:
                logger.warning("Frontman generate response (%s): <unserializable>", provider)
        else:
            messages = ChatAIService._messages_to_chat_messages(history, system_text=lead_text)
            resp = get_client("xai").chat.completions.create(
                model=model_name,
                messages=messages,
                tools=ModuleDirectory.function_tool_specs(),
                tool_choice="none",
            )
            assistant_text = ""
            if getattr(resp, "choices", None):
                assistant_text = resp.choices[0].message.content or ""  # type: ignore[assignment]
            usage_obj = getattr(resp, "usage", None)
            logger.warning("Frontman generate response (%s): %s", provider, resp)

        if usage_obj:
            UsageService.log_usage(
                source="frontman_generate",
                model=model_name,
                cache_mode=cache_mode,
                usage=usage_obj,
                prompt_cache_key=prompt_cache_key,
                job=None,
            )

        return assistant_text

    @staticmethod
    def frontman_decision(
        context: Dict[str, Any],
        model: str | None = None,
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
            "Decision rule: If the user only needs conversation or analysis (including discussing data already shown in recent messages), reply directly. "
            "If fresh action/data is needed, do NOT answer; instead emit a JSON handoff object.\n"
            "Handoff JSON shape:\n"
            '{\"handoff\":true,\"reason\":\"why\",\"module_hint\":\"optional\"}\n'
            "If not handing off, return {\"handoff\":false,\"reply\":\"your message\"}.\n"
            "Keep JSON terse. No extra prose outside the JSON."
        )

        if module_text:
            instructions += f"\nAvailable modules:\n{module_text}"

        model_name = model or ModelConfigService.get_frontman_model()
        cache_mode = ModelConfigService.get_cache_mode()
        provider = resolve_provider(model_name)
        prompt_cache_key = ""
        usage_obj = None
        assistant_text = ""

        if provider == "openai":
            input_seq = ChatAIService._messages_to_openai_input(history, lead_developer_text=instructions)
            resp_kwargs = {
                "model": model_name,
                "input": input_seq,
                "text": {"format": {"type": "text"}, "verbosity": "medium"},
                "reasoning": {"effort": "low"},
                "tools": [],
                "store": True,
            }
            if cache_mode in ("frontman", "all"):
                persona_key = getattr(PersonaService.get_persona(), "slug", "default") or "default"
                module_key = "-".join(sorted(m["slug"] for m in module_lines)) if module_lines else "none"
                key_hash = hashlib.md5(f"{persona_key}|{module_key}".encode("utf-8")).hexdigest()
                prompt_cache_key = f"fmv1-{key_hash}"
                resp_kwargs["prompt_cache_key"] = prompt_cache_key
            resp = get_client("openai").responses.create(**resp_kwargs)
            assistant_text = getattr(resp, "output_text", None) or ""
            usage_obj = getattr(resp, "usage", None)
            try:
                raw = (
                    resp.model_dump()
                    if hasattr(resp, "model_dump")
                    else resp.to_dict()
                    if hasattr(resp, "to_dict")
                    else str(resp)
                )
                logger.warning("Frontman decision response (%s): %s", provider, raw)
            except Exception:
                logger.warning("Frontman decision response (%s): <unserializable>", provider)
        else:
            messages = ChatAIService._messages_to_chat_messages(history, system_text=instructions)
            resp = get_client("xai").chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"},
            )
            if getattr(resp, "choices", None):
                assistant_text = resp.choices[0].message.content or ""  # type: ignore[assignment]
            usage_obj = getattr(resp, "usage", None)
            logger.warning("Frontman decision response (%s): %s", provider, resp)

        if usage_obj:
            UsageService.log_usage(
                source="frontman_decision",
                model=model_name,
                cache_mode=cache_mode,
                usage=usage_obj,
                prompt_cache_key=prompt_cache_key,
                job=None,
            )

        return assistant_text

    @staticmethod
    def summarize_scheduled_task(context_text: str, model: str | None = None) -> str:
        """
        Generate a short, human-readable TL;DR for a scheduled task run.
        """
        instructions = (
            "You are Frontman. Summarize the scheduled task execution based on the provided "
            "function-caller context. The summary must be short, concise, and human-readable. "
            "Limit to 1-2 sentences."
        )

        model_name = model or ModelConfigService.get_frontman_model()
        provider = resolve_provider(model_name)

        if provider == "openai":
            input_seq = [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": instructions}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": context_text}],
                },
            ]
            resp = get_client("openai").responses.create(
                model=model_name,
                input=input_seq,
                text={"format": {"type": "text"}, "verbosity": "low"},
                reasoning={"effort": "low"},
                tools=[],
                store=False,
                timeout=30,
            )
            return (getattr(resp, "output_text", None) or "").strip()

        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": context_text},
        ]
        resp = get_client("xai").chat.completions.create(
            model=model_name,
            messages=messages,
            timeout=30,
        )
        if getattr(resp, "choices", None):
            return (resp.choices[0].message.content or "").strip()  # type: ignore[assignment]
        return ""

    @staticmethod
    def summarize_call(context_text: str, model: str | None = None) -> str:
        """
        Summarize a call transcript and outcome in 1-2 sentences.
        """
        instructions = (
            "You are Frontman. Summarize the call transcript and whether the goal was achieved. "
            "Be short, concise, and human-readable. Limit to 1-2 sentences."
        )

        model_name = model or ModelConfigService.get_frontman_model()
        provider = resolve_provider(model_name)

        if provider == "openai":
            input_seq = [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": instructions}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": context_text}],
                },
            ]
            resp = get_client("openai").responses.create(
                model=model_name,
                input=input_seq,
                text={"format": {"type": "text"}, "verbosity": "low"},
                reasoning={"effort": "low"},
                tools=[],
                store=False,
                timeout=30,
            )
            return (getattr(resp, "output_text", None) or "").strip()

        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": context_text},
        ]
        resp = get_client("xai").chat.completions.create(
            model=model_name,
            messages=messages,
            timeout=30,
        )
        if getattr(resp, "choices", None):
            return (resp.choices[0].message.content or "").strip()  # type: ignore[assignment]
        return ""

    @staticmethod
    def summarize_tool_result_context(
        context_text: str,
        model: str | None = None,
    ) -> Dict[str, Any]:
        """
        Compress tool output into structured memory that preserves actionable facts.
        """
        instructions = (
            "You are compressing tool output for future AI context. Preserve useful facts while removing noise. "
            "Return JSON only with keys: summary, key_facts, important_ids, warnings. "
            "summary must be 1-2 short sentences. key_facts must be a short list of concrete facts or counts. "
            "important_ids should contain only identifiers that may matter in later steps. warnings should list blockers, risks, or ambiguities. "
            "Do not invent facts. If data is missing, say so briefly."
        )

        model_name = model or ModelConfigService.get_caller_model()
        provider = resolve_provider(model_name)

        try:
            if provider == "openai":
                input_seq = [
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": instructions}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": context_text}],
                    },
                ]
                resp = get_client("openai").responses.create(
                    model=model_name,
                    input=input_seq,
                    text={"format": {"type": "json_object"}},
                    reasoning={"effort": "low"},
                    tools=[],
                    store=False,
                    timeout=30,
                )
                raw = getattr(resp, "output_text", "{}") or "{}"
                data = json.loads(raw)
                if isinstance(data, dict):
                    return {
                        "summary": str(data.get("summary") or "").strip(),
                        "key_facts": [str(item).strip() for item in (data.get("key_facts") or []) if str(item).strip()],
                        "important_ids": [str(item).strip() for item in (data.get("important_ids") or []) if str(item).strip()],
                        "warnings": [str(item).strip() for item in (data.get("warnings") or []) if str(item).strip()],
                    }
            else:
                messages = [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": context_text},
                ]
                resp = get_client("xai").chat.completions.create(
                    model=model_name,
                    messages=messages,
                    response_format={"type": "json_object"},
                    timeout=30,
                )
                if getattr(resp, "choices", None):
                    raw = resp.choices[0].message.content or "{}"  # type: ignore[assignment]
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        return {
                            "summary": str(data.get("summary") or "").strip(),
                            "key_facts": [str(item).strip() for item in (data.get("key_facts") or []) if str(item).strip()],
                            "important_ids": [str(item).strip() for item in (data.get("important_ids") or []) if str(item).strip()],
                            "warnings": [str(item).strip() for item in (data.get("warnings") or []) if str(item).strip()],
                        }
        except Exception:
            logger.exception("Failed to summarize tool result context")

        return {
            "summary": "Tool call completed.",
            "key_facts": [],
            "important_ids": [],
            "warnings": [],
        }

    @staticmethod
    def should_end_call(context_text: str, model: str | None = None) -> bool:
        """
        Decide whether a call should end now based on the transcript and goal.
        """
        instructions = (
            "You are a call monitor. Decide if the call should end now based on the goal and transcript. "
            "Respond with exactly one word: END or CONTINUE."
        )

        model_name = model or ModelConfigService.get_frontman_model()
        provider = resolve_provider(model_name)

        if provider == "openai":
            input_seq = [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": instructions}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": context_text}],
                },
            ]
            resp = get_client("openai").responses.create(
                model=model_name,
                input=input_seq,
                text={"format": {"type": "text"}, "verbosity": "low"},
                reasoning={"effort": "low"},
                tools=[],
                store=False,
                timeout=20,
            )
            output = (getattr(resp, "output_text", None) or "").strip().upper()
            return output.startswith("END")

        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": context_text},
        ]
        resp = get_client("xai").chat.completions.create(
            model=model_name,
            messages=messages,
            timeout=20,
        )
        if getattr(resp, "choices", None):
            content = (resp.choices[0].message.content or "").strip().upper()  # type: ignore[assignment]
            return content.startswith("END")
        return False

    @staticmethod
    def phrase_inbox_message(
        body: str,
        *,
        title: str = "",
        kind: str = "info",
        model: str | None = None,
    ) -> str:
        """
        Rephrase a draft inbox message in the Frontman voice without changing meaning.
        """
        if not body or not body.strip():
            return body
        persona_text = PersonaService.build_persona_prompt()
        instructions = (
            f"{persona_text}\n\n"
            "Rewrite the draft message in the Frontman voice. Keep the meaning and facts. "
            "Be short and to the point (1-2 sentences). Do not add new info. "
            "Return only the final message text. The original message might reference the user, but your text will be sent to them directly. "
            "So keep that in mind. Address the user directly to the user. Mention them by name when appropriate."
        )
        context_text = f"Kind: {kind}\nTitle: {title}\nDraft: {body}"
        model_name = model or ModelConfigService.get_frontman_model()
        provider = resolve_provider(model_name)

        if provider == "openai":
            input_seq = [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": instructions}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": context_text}],
                },
            ]
            resp = get_client("openai").responses.create(
                model=model_name,
                input=input_seq,
                text={"format": {"type": "text"}, "verbosity": "low"},
                reasoning={"effort": "low"},
                tools=[],
                store=False,
                timeout=20,
            )
            return (getattr(resp, "output_text", None) or "").strip() or body

        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": context_text},
        ]
        resp = get_client("xai").chat.completions.create(
            model=model_name,
            messages=messages,
            timeout=20,
        )
        if getattr(resp, "choices", None):
            return (resp.choices[0].message.content or "").strip() or body  # type: ignore[assignment]
        return body

    @staticmethod
    def transcribe_audio(
        audio_file_path: str,
        model: str | None = None,
        language: str | None = None,
    ) -> str:
        """
        Transcribe audio without translating it. An explicit ISO-639-1 language
        prevents short clips from being misdetected as another language.
        """
        model_name = model or settings.transcription_model
        request_args = {
            "model": model_name,
            "prompt": "Transcribe verbatim in the original spoken language. Do not translate into another language.",
        }
        if language:
            request_args["language"] = language
        # GPT-4o transcription models return a JSON object; Whisper also
        # supports plain text and remains usable when explicitly configured.
        request_args["response_format"] = "text" if model_name == "whisper-1" else "json"
        with open(audio_file_path, "rb") as audio_file:
            transcription = get_client("openai").audio.transcriptions.create(
                file=audio_file,
                **request_args,
            )
        if isinstance(transcription, str):
            return transcription.strip()
        return (getattr(transcription, "text", None) or "").strip()
