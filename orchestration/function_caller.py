from __future__ import annotations

import json
from json import JSONDecoder
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

from Corv.config import settings
from orchestration.model_providers import resolve_provider, get_client
from orchestration.services import (
    ModuleDirectory,
    FunctionRunnerService,
    JobService,
    ModelConfigService,
    PersonaService,
    UsageService,
)
from orchestration.models import Job
from orchestration.schemas import FunctionCallPayload
from orchestration.message_router import MessageRouter

logger = logging.getLogger(__name__)


class FunctionCallOrchestrator:
    """
    Iterative Function Caller that plans and executes tool calls using manifests from the DB.
    """

    @staticmethod
    def _plan_next_action(
        *,
        user_request: str,
        tool_catalog: List[Dict[str, Any]],
        prior_results: List[Dict[str, Any]],
        model: str = "gpt-5-mini",
        cache_mode: str = "off",
        job: Optional[Job] = None,
        chat_id: Optional[str] = None,
        call_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ask the model to decide the next function call (or finish/ask user) with strict JSON.
        """
        module_hints = {}
        for t in tool_catalog:
            hint = t.get("module_caller_instructions")
            if hint:
                module_hints.setdefault(t["module"], hint)

        # Calendar defaults to reduce redundant asks.
        calendar_defaults = []
        if settings.google_calendar_default_id:
            calendar_defaults.append(
                f"Use calendar_id='{settings.google_calendar_default_id}' if none provided."
            )
        if settings.google_calendar_default_timezone:
            calendar_defaults.append(
                f"Use timezone '{settings.google_calendar_default_timezone}' if none provided; do not ask for it when listing events."
            )

        tools_text = "\n".join(
            f"- {t['manifest_id']} (module: {t['module']}): {t['description']} | params: {list((t.get('params_schema') or {}).get('properties', {}).keys())}"
            for t in tool_catalog
        )
        module_hints_text = (
            "\n".join(f"- {mod}: {hint}" for mod, hint in module_hints.items())
            if module_hints
            else "None"
        )
        defaults_text = "\n".join(calendar_defaults) if calendar_defaults else "None"
        ssh_context = "None"
        if any(str(tool.get("manifest_id", "")).startswith("ssh_connections.") for tool in tool_catalog):
            # Machine notes are durable user-managed operational context. Load them
            # before planning so selection and the very first command can respect them.
            from ssh_connections.models import SshMachine

            lines = []
            for machine in SshMachine.objects.order_by("-is_default", "name")[:30]:
                notes = machine.notes.strip() or "No machine-specific notes."
                lines.append(
                    f"- {machine.name} (id={machine.pk}; "
                    f"default={'yes' if machine.is_default else 'no'}; "
                    f"Corv commands={'allowed' if machine.allow_ai_commands else 'disabled'}): "
                    f"{notes[:4000]}"
                )
            ssh_context = "\n".join(lines) if lines else "No saved SSH machines."
        conversation_delegations = "None"
        if chat_id or call_session_id:
            from coding.chat_waits import CodingChatWaitService
            if chat_id:
                from chat.models import Chat
                origin = {"chat": Chat.objects.filter(pk=chat_id).first()}
            else:
                from orchestration.models import CallSession
                origin = {"call_session": CallSession.objects.filter(pk=call_session_id).first()}
            if all(origin.values()):
                conversation_delegations = json.dumps(CodingChatWaitService.list_for_origin(**origin), ensure_ascii=False)
        results_text = json.dumps(prior_results, ensure_ascii=False)
        presentation_rules = FunctionCallOrchestrator._presentation_instructions(
            chat_id=chat_id, call_session_id=call_session_id
        )
        # The caller is separate from the Frontman and needs its persisted context.
        shared_context = PersonaService.build_persona_prompt()
        instructions = (
            "You are the Function Caller. Decide one step at a time whether to call a function, ask the user, or finish.\n"
            "Module hints to respect when planning:\n"
            f"{module_hints_text}\n"
            "Module defaults:\n"
            f"{defaults_text}\n"
            "Saved SSH machine context (user-maintained operational notes; take these into "
            "account when choosing a machine and constructing commands):\n"
            f"{ssh_context}\n"
            "Functions available:\n"
            f"{tools_text}\n\n"
            "Delegations from this conversation (independently waitable):\n"
            f"{conversation_delegations}\n\n"
            "Return exactly ONE JSON object and nothing else, using this exact shape: "
            '{"done":bool,'
            '"call": {"function_id": "...", "params": {...}} or null,'
            '"ask_user": "question text" or null,'
            '"summary": "short summary"}\n'
            "Rules:\n"
            "- Plan exactly one step per response. Never concatenate JSON objects, emit a sequence of actions, "
            "put function_id/params at the top level, or describe a later call as though it already happened. "
            "When a call is needed, set done=false and place that single action inside call. The orchestrator "
            "will execute it and invoke you again with its actual result in prior_results.\n"
            "- Only use function_ids from the catalog.\n"
            "- If you need output from a previous call, it is in prior_results.\n"
            "- prior_results may contain context_summary when raw tool output was compressed; treat that summary as the trusted distilled memory of the call.\n"
            "- If you need user input, set ask_user and done=true.\n"
            "- Do NOT fabricate data; only summarize actual function results in prior_results.\n"
            "- If you lack the data, propose the function call to get it (do not mark done with a fabricated summary).\n"
            "- Search before unknown: never finish with a summary saying or implying that you do not know, cannot recall, or lack information unless the appropriate search already appears in prior_results and returned no answer or an explicit failure. For personal facts, preferences, people, places, or user history, call user_info.search_knowledge first. For general/public/current knowledge, call internet_search.search. If ambiguous, search personal knowledge first, then internet search if needed.\n"
            "- Semantic-first personal retrieval: call user_info.search_knowledge with the natural-language query and a useful result limit (normally 10). Do not add tags, source, entity type, user_id, or any other deterministic filter unless the user explicitly requested that exact constraint. Filters are hard exclusions, not semantic hints. If an explicitly filtered search returns no result, retry once without filters before concluding the knowledge is absent. Preserve the top relevant result payloads in prior_results for reasoning.\n"
            "- Before any note create/update, first search_knowledge broadly for the subject and related facts, inspect the relevant results, and reuse the existing tag vocabulary where appropriate. This is a multi-turn planner flow: first return ONLY the search call; after its result appears in prior_results, return ONLY the create/update call; after that result appears, return done=true with no call. Never output all three decisions together. Do not repeat a successful identical search already present in prior_results. Store time-stable facts. In note content, EVERY temporal reference must be absolute: replace today, tonight, tomorrow, yesterday, now, currently, this morning, next week, ago, 'in X days', and similar wording with exact calendar dates and, when relevant and known, times/timezones. Express durations with explicit start/end dates. Keep morning/night only with an exact date if no clock time was supplied, and never invent a clock time. Save birth date/year instead of current age. If a changing status is unavoidable, include an exact as-of date/time or expires_at. Before calling add_note/update_note, scan content and rewrite every relative temporal expression.\n"
            "- General knowledge and current facts: when the answer is uncertain, likely changed, or the user asks "
            "to look up, verify, search, or find online information, call internet_search.search before answering. "
            "Use its answer and source URLs in the final summary. Do not use internet search for the user's private "
            "data or as a substitute for a more specific Corv module.\n"
            "- If no function needed, set done=true and summary.\n"
            f"{presentation_rules}\n"
            "- SSH routing: if the user names, describes, or clearly refers to a particular saved "
            "machine, include that machine's exact saved name or id in every related SSH call. "
            "Never omit machine merely because a different machine is marked default.\n"
            "- Codex delegation (strong default): delegate any find, locate, search, or discovery of a "
            "project, repository, file, or unknown path to coding_sessions, as well as repository work, "
            "multi-step debugging, implementation, tests, and non-text file generation. Do not start "
            "those tasks with ssh_connections.run_command. For a named machine, reuse or create a coding "
            "session on that exact machine first. Direct SSH is only for a known exact path and a single "
            "bounded command or status check.\n"
            "- New delegate_task and delegate_feature work waits by default: do not ask permission to wait. Omit wait_for_completion or pass true unless the user explicitly asks to continue without waiting.\n"
            "- Use list_conversation_delegations for concurrent work and set_conversation_delegation_wait to interrupt, resume, or switch a specific wait. Never poll repeatedly; questions are always surfaced.\n"
            "- SSH routing: omit machine to use the default only when the user expressed no machine "
            "preference. If the requested machine is ambiguous, unrecognized, or suitability must "
            "be compared, call ssh_connections.list_machines first and select from its result.\n\n"
            "Shared Frontman context (trusted background about the user and their "
            "preferences; use it when relevant, but the Function Caller role and "
            "rules above take precedence):\n"
            f"{shared_context}"
        )

        input_seq = [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": instructions}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": f"User request: {user_request}"}
                ],
            },
            {
                "role": "system",
                "content": [
                    {"type": "input_text", "text": f"Prior results: {results_text}"}
                ],
            },
        ]

        provider = resolve_provider(model)
        prompt_cache_key = ""
        usage_obj = None
        raw = "{}"

        if provider == "openai":
            resp_kwargs = {
                "model": model,
                "input": input_seq,
                "tools": [],
                "text": {"format": {"type": "json_object"}},
                "reasoning": {"effort": "low"},
                "timeout": 30,
            }
            if cache_mode in ("caller", "all"):
                # Stable key based on the planner instructions and tool catalog shape.
                catalog_sig = hashlib.md5(
                    "|".join(sorted(t["manifest_id"] for t in tool_catalog)).encode("utf-8")
                ).hexdigest()
                prompt_cache_key = f"caller-v10-{catalog_sig}"
                resp_kwargs["prompt_cache_key"] = prompt_cache_key
            resp = get_client("openai").responses.create(**resp_kwargs)
            usage_obj = getattr(resp, "usage", None)
            raw = getattr(resp, "output_text", "{}") or "{}"
        else:
            messages = [
                {
                    "role": "system",
                    "content": instructions,
                },
                {
                    "role": "user",
                    "content": f"User request: {user_request}",
                },
                {
                    "role": "user",
                    "content": f"Prior results: {results_text}",
                },
            ]
            resp = get_client("xai").chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                timeout=30,
            )
            usage_obj = getattr(resp, "usage", None)
            if getattr(resp, "choices", None):
                raw = resp.choices[0].message.content or "{}"  # type: ignore[assignment]

        if usage_obj:
            UsageService.log_usage(
                source="caller_plan",
                model=model,
                cache_mode=cache_mode,
                usage=usage_obj,
                prompt_cache_key=prompt_cache_key,
                job=job,
            )
        decision = FunctionCallOrchestrator._safe_json_load(raw)
        if not decision:
            decision = {"done": True, "summary": "Planner output could not be parsed."}
        if job:
            MessageRouter.tool_only_note(
                chat_id=chat_id,
                content=f"Planner raw: {raw}\nParsed: {decision}",
                role="caller",
                job=job,
            )
        return decision

    @staticmethod
    def _presentation_instructions(*, chat_id=None, call_session_id=None) -> str:
        if call_session_id:
            return (
                "- Spoken call output: summary must be short, natural speech in plain text. Never emit or "
                "speak Markdown syntax, headings, bullets, raw URLs, or link notation."
            )
        if chat_id:
            return (
                "- Text-chat presentation: final summary is the user-facing answer. Format it as polished, "
                "concise GitHub-flavored Markdown when structure helps: a short descriptive heading for a "
                "multi-part answer, compact bullets for distinct items, and [descriptive source](https://...) "
                "links near supported claims. Use source URLs preserved in prior_results; never replace them "
                "with unlinked site names. Do not mention internal tool status or over-format simple answers."
            )
        return "- Operational output: keep summary concise and plain."

    @staticmethod
    def _extract_sources_for_context(value: Any, *, limit: int = 12) -> List[Dict[str, str]]:
        from urllib.parse import urlparse
        found: List[Dict[str, str]] = []
        seen = set()

        def walk(node: Any):
            if len(found) >= limit:
                return
            if isinstance(node, dict):
                candidate = str(node.get("url") or "").strip()
                if candidate:
                    parsed = urlparse(candidate)
                    if parsed.scheme in ("http", "https") and parsed.netloc and candidate not in seen:
                        seen.add(candidate)
                        title = str(node.get("title") or node.get("name") or parsed.netloc).strip()
                        found.append({"title": title[:300], "url": candidate, "site_name": parsed.netloc.removeprefix("www.")})
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(value)
        return found

    @staticmethod
    def _remember_job_sources(job: Optional[Job], sources: List[Dict[str, str]]):
        if not job or not sources:
            return
        job.refresh_from_db(fields=["metadata"])
        metadata = job.metadata if isinstance(job.metadata, dict) else {}
        existing = [item for item in metadata.get("pending_sources", []) if isinstance(item, dict)]
        by_url = {str(item.get("url")): item for item in existing if item.get("url")}
        for source in sources:
            by_url[source["url"]] = source
        metadata["pending_sources"] = list(by_url.values())[:12]
        job.metadata = metadata
        job.save(update_fields=["metadata", "updated_at"])

    @staticmethod
    def _safe_json_load(text: str) -> Dict[str, Any]:
        decoder = JSONDecoder()
        idx = 0
        first_obj = None
        text_len = len(text)
        while idx < text_len:
            # Skip whitespace
            while idx < text_len and text[idx].isspace():
                idx += 1
            if idx >= text_len:
                break
            try:
                obj, end = decoder.raw_decode(text, idx)
                if first_obj is None:
                    first_obj = (
                        obj  # prefer the first well-formed JSON object (the decision)
                    )
                idx = end
            except json.JSONDecodeError:
                # Move forward to next brace and try again
                next_brace = text.find("{", idx + 1)
                if next_brace == -1:
                    break
                idx = next_brace
                continue
        if isinstance(first_obj, dict):
            # Older/smaller planners occasionally emit the historical single-call
            # shape. Normalize it rather than silently spending a loop iteration.
            if first_obj.get("function_id") and "call" not in first_obj:
                return {
                    "done": False,
                    "call": {
                        "function_id": first_obj["function_id"],
                        "params": first_obj.get("params") or {},
                    },
                    "ask_user": None,
                    "summary": first_obj.get("summary") or "",
                }
            return first_obj
        # Fallback: try first balanced braces
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        return {"done": True, "summary": "Planner output could not be parsed."}

    @staticmethod
    def _extract_ids_for_context(value: Any, *, limit: int = 12) -> List[str]:
        found: List[str] = []

        def walk(node: Any):
            if len(found) >= limit:
                return
            if isinstance(node, dict):
                for key, val in node.items():
                    lowered = str(key).lower()
                    if lowered.endswith("id") or lowered.endswith("_id") or lowered == "id":
                        text = str(val).strip()
                        if text and text not in found:
                            found.append(text)
                            if len(found) >= limit:
                                return
                    walk(val)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(value)
        return found

    @staticmethod
    def _compact_result_context(
        *,
        function_id: str,
        params: Dict[str, Any],
        status: str,
        data: Any,
        error: Optional[str],
    ) -> Dict[str, Any]:
        payload = {
            "function_id": function_id,
            "status": status,
            "params": params,
            "error": error,
            "data": data,
        }
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        use_ai_summary = len(serialized) > 900
        summary_text = f"{function_id} returned status={status}."
        key_facts: List[str] = []
        warnings: List[str] = [str(error)] if error else []
        important_ids = FunctionCallOrchestrator._extract_ids_for_context(data)

        if isinstance(data, dict):
            for key, value in list(data.items())[:10]:
                if isinstance(value, list):
                    key_facts.append(f"{key}: {len(value)} items")
                elif isinstance(value, dict):
                    key_facts.append(f"{key}: {len(value)} fields")
                elif value is not None and value != "":
                    key_facts.append(f"{key}: {str(value)[:120]}")
        elif isinstance(data, list):
            key_facts.append(f"Returned list with {len(data)} items")
        elif data is not None:
            key_facts.append(str(data)[:160])

        if use_ai_summary:
            try:
                from openai_integration.services import ChatAIService

                ai_summary = ChatAIService.summarize_tool_result_context(serialized)
                summary_text = ai_summary.get("summary") or summary_text
                key_facts = ai_summary.get("key_facts") or key_facts
                important_ids = ai_summary.get("important_ids") or important_ids
                warnings = ai_summary.get("warnings") or warnings
            except Exception:
                logger.exception("Failed to build AI context summary for %s", function_id)

        return {
            "summary": summary_text,
            "key_facts": key_facts[:8],
            "important_ids": important_ids[:12],
            "warnings": warnings[:6],
            "used_ai_summary": use_ai_summary,
        }

    @staticmethod
    def _coerce_result_payload(
        result: FunctionResultPayload,
        *,
        function_id: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Ensure the stored result is bounded so the next prompt doesn't explode.
        """
        data = result.data
        coerced = {
            "function_id": function_id,
            "params": params,
            "status": result.status,
            "data": data,
            "error": result.error_summary,
            "sources": FunctionCallOrchestrator._extract_sources_for_context(data),
        }
        coerced["context_summary"] = FunctionCallOrchestrator._compact_result_context(
            function_id=function_id,
            params=params,
            status=result.status,
            data=data,
            error=result.error_summary,
        )
        if data is None:
            coerced["data"] = None
            coerced["truncated"] = False
            return coerced

        try:
            serialized = json.dumps(data, ensure_ascii=False, default=str)
            max_chars = ModelConfigService.get_max_function_result_chars()
            if len(serialized) > max_chars:
                coerced["data"] = {
                    "summary": coerced["context_summary"].get("summary"),
                    "key_facts": coerced["context_summary"].get("key_facts", []),
                    "important_ids": coerced["context_summary"].get("important_ids", []),
                    "warnings": coerced["context_summary"].get("warnings", []),
                }
                coerced["truncated"] = True
                coerced["truncation_reason"] = (
                    f"Result compressed for context ({len(serialized)} chars > limit {max_chars})."
                )
                return coerced
        except Exception:
            pass
        coerced["truncated"] = False
        return coerced

    @staticmethod
    def _summarize_result_for_log(
        result: FunctionResultPayload,
        *,
        context_summary: Optional[Dict[str, Any]] = None,
        truncated: bool = False,
        truncation_reason: str = "",
        limit: int = 2000,
    ) -> str:
        """
        Text for tool-only log messages, truncated to avoid stuffing chat context.
        If truncated=True, emit only status + reason (no payload).
        """
        if context_summary:
            lines = [str(context_summary.get("summary") or result.status.upper()).strip()]
            key_facts = [str(item).strip() for item in (context_summary.get("key_facts") or []) if str(item).strip()]
            warnings = [str(item).strip() for item in (context_summary.get("warnings") or []) if str(item).strip()]
            if key_facts:
                lines.append("Key facts: " + "; ".join(key_facts[:5]))
            if warnings:
                lines.append("Warnings: " + "; ".join(warnings[:3]))
            text = "\n".join(lines).strip()
            if text:
                return text[:limit]
        if truncated:
            reason = truncation_reason or "Result too large; data dropped."
            return f"{result.status.upper()}: {reason}"

        import json

        try:
            payload = result.model_dump()
        except Exception:
            payload = {
                "status": result.status,
                "error_summary": result.error_summary,
            }
        text = json.dumps(payload, default=str, ensure_ascii=False)
        if len(text) > limit:
            return f"{text[:limit]}... [truncated {len(text) - limit} chars]"
        return text

    @staticmethod
    def run(chat_context: Dict[str, Any], job: Job, max_steps: int = 5) -> str:
        tool_catalog = ModuleDirectory.function_catalog()
        # Build a brief recent-context string (last 10 messages).
        messages = chat_context.get("messages") or []
        recent = messages[-10:] if len(messages) > 10 else messages
        ctx_lines = []
        for m in recent:
            prefix = (
                "User"
                if m.role == "user"
                else "Assistant" if m.role == "assistant" else "Tool"
            )
            ts = (
                f"[{m.created_at.isoformat()}] "
                if getattr(m, "created_at", None)
                else ""
            )
            ctx_lines.append(f"{prefix}: {ts}{m.text}")
        user_request = "\n".join(ctx_lines) if ctx_lines else ""

        prior_results: List[Dict[str, Any]] = []

        try:
            model_name = ModelConfigService.get_caller_model()
            cache_mode = ModelConfigService.get_cache_mode()
            for step in range(max_steps):
                if job.cancel_requested or job.status == Job.STATUS_CANCELED:
                    JobService.mark_status(job, Job.STATUS_CANCELED)
                    MessageRouter.tool_only_note(
                        chat_id=job.chat.id if job.chat else None,
                        content="Job canceled mid-run; stopping immediately.",
                        role="caller",
                        job=job,
                    )
                    return "Job canceled."

                decision = FunctionCallOrchestrator._plan_next_action(
                    user_request=user_request,
                    tool_catalog=tool_catalog,
                    prior_results=prior_results,
                    job=job,
                    chat_id=job.chat.id if job and job.chat else None,
                    model=model_name,
                    cache_mode=cache_mode,
                )

                if decision.get("ask_user"):
                    # Pause and request input via Front Man.
                    JobService.mark_status(job, Job.STATUS_WAITING_USER)
                    MessageRouter.frontman_update(
                        chat_id=job.chat.id if job.chat else None,
                        content=decision["ask_user"],
                        job=job,
                        message_type="user_visible",
                    )
                    MessageRouter.tool_only_note(
                        chat_id=job.chat.id if job.chat else None,
                        content=f"Planner asked user: {decision['ask_user']}",
                        role="caller",
                        job=job,
                    )
                    # Stash state so we can resume later.
                    job.metadata = job.metadata or {}
                    job.metadata["pending_state"] = {
                        "user_request": user_request,
                        "prior_results": prior_results,
                    }
                    job.save(update_fields=["metadata", "updated_at"])
                    return decision["ask_user"]

                call = decision.get("call")
                if call and call.get("function_id"):
                    payload = FunctionCallPayload(
                        trace_id=job.trace_id,
                        function_id=call["function_id"],
                        params=call.get("params") or {},
                        job_id=str(job.id),
                    )
                    MessageRouter.tool_only_note(
                        chat_id=job.chat.id if job.chat else None,
                        content=f"Calling {payload.function_id} with params: {payload.params}",
                        role="caller",
                        job=job,
                        metadata={"include_in_context": False, "kind": "tool_call"},
                    )
                    result = FunctionRunnerService.run_function_call(payload, job=job)
                    coerced = FunctionCallOrchestrator._coerce_result_payload(
                        result,
                        function_id=call["function_id"],
                        params=call.get("params") or {},
                    )
                    coerced["function_id"] = call["function_id"]
                    coerced["params"] = call.get("params") or {}
                    prior_results.append(coerced)
                    FunctionCallOrchestrator._remember_job_sources(job, coerced.get("sources") or [])
                    if coerced.get("truncated"):
                        MessageRouter.tool_only_note(
                            chat_id=job.chat.id if job.chat else None,
                            content=coerced.get(
                                "truncation_reason", "Result truncated for size"
                            ),
                            role="caller",
                            job=job,
                            metadata={"include_in_context": False, "kind": "truncation_notice"},
                        )
                    MessageRouter.tool_only_note(
                        chat_id=job.chat.id if job.chat else None,
                        content=f"Function result: {FunctionCallOrchestrator._summarize_result_for_log(result, context_summary=coerced.get('context_summary'), truncated=coerced.get('truncated', False), truncation_reason=coerced.get('truncation_reason', ''))}",
                        role="runner",
                        job=job,
                        call_id=result.call_id,
                        metadata={"include_in_context": True, "kind": "function_result_summary"},
                    )
                    job.updated_at = (
                        job.updated_at
                    )  # no-op placeholder to avoid stale writes
                    job.save(update_fields=["updated_at"])
                    continue

                # No call; either done or unable to proceed.
                if decision.get("done"):
                    break

        except Exception as exc:  # pragma: no cover
            logger.exception("Function caller crashed")
            err = f"Function Caller error: {exc}"
            MessageRouter.tool_only_note(
                chat_id=job.chat.id if job and job.chat else None,
                content=err,
                role="caller",
                job=job,
            )
            MessageRouter.frontman_update(
                chat_id=job.chat.id if job and job.chat else None,
                content="The job failed due to an internal error. Please try again.",
                job=job,
                message_type="user_visible",
            )
            JobService.mark_status(job, Job.STATUS_FAILED, error_summary=str(exc))
            return "Job failed."

        summary = ""
        if prior_results:
            summary = decision.get("summary") or "Completed."
        else:
            summary = decision.get("summary") or "No actions taken."

        return summary

    @staticmethod
    def resume(
        chat_context: Dict[str, Any], job: Job, user_response: str, max_steps: int = 5
    ) -> str:
        """
        Resume a waiting-on-user job using stored pending_state.
        """
        state = (job.metadata or {}).get("pending_state") or {}
        prior_results = state.get("prior_results") or []
        base_request = state.get("user_request") or ""
        # Rebuild recent context for better continuity.
        messages = chat_context.get("messages") or []
        recent = messages[-10:] if len(messages) > 10 else messages
        ctx_lines = []
        for m in recent:
            prefix = (
                "User"
                if m.role == "user"
                else "Assistant" if m.role == "assistant" else "Tool"
            )
            ts = (
                f"[{m.created_at.isoformat()}] "
                if getattr(m, "created_at", None)
                else ""
            )
            ctx_lines.append(f"{prefix}: {ts}{m.text}")
        ctx_lines.append(f"User (new): {user_response}")
        user_request = "\n".join(ctx_lines)
        tool_catalog = ModuleDirectory.function_catalog()

        try:
            model_name = ModelConfigService.get_caller_model()
            cache_mode = ModelConfigService.get_cache_mode()
            for step in range(max_steps):
                if job.cancel_requested or job.status == Job.STATUS_CANCELED:
                    JobService.mark_status(job, Job.STATUS_CANCELED)
                    MessageRouter.tool_only_note(
                        chat_id=job.chat.id if job.chat else None,
                        content="Job canceled mid-resume; stopping immediately.",
                        role="caller",
                        job=job,
                    )
                    return "Job canceled."

                decision = FunctionCallOrchestrator._plan_next_action(
                    user_request=user_request,
                    tool_catalog=tool_catalog,
                    prior_results=prior_results,
                    job=job,
                    chat_id=job.chat.id if job and job.chat else None,
                    model=model_name,
                    cache_mode=cache_mode,
                )

                if decision.get("ask_user"):
                    MessageRouter.frontman_update(
                        chat_id=job.chat.id if job.chat else None,
                        content=decision["ask_user"],
                        job=job,
                        message_type="user_visible",
                    )
                    MessageRouter.tool_only_note(
                        chat_id=job.chat.id if job.chat else None,
                        content=f"Planner asked user: {decision['ask_user']}",
                        role="caller",
                        job=job,
                    )
                    job.metadata = job.metadata or {}
                    job.metadata["pending_state"] = {
                        "user_request": base_request,
                        "prior_results": prior_results,
                    }
                    job.save(update_fields=["metadata", "updated_at"])
                    JobService.mark_status(job, Job.STATUS_WAITING_USER)
                    return decision["ask_user"]

                call = decision.get("call")
                if call and call.get("function_id"):
                    payload = FunctionCallPayload(
                        trace_id=job.trace_id,
                        function_id=call["function_id"],
                        params=call.get("params") or {},
                        job_id=str(job.id),
                    )
                    MessageRouter.tool_only_note(
                        chat_id=job.chat.id if job.chat else None,
                        content=f"Calling {payload.function_id} with params: {payload.params}",
                        role="caller",
                        job=job,
                        metadata={"include_in_context": False, "kind": "tool_call"},
                    )
                    result = FunctionRunnerService.run_function_call(payload, job=job)
                    coerced = FunctionCallOrchestrator._coerce_result_payload(
                        result,
                        function_id=call["function_id"],
                        params=call.get("params") or {},
                    )
                    coerced["function_id"] = call["function_id"]
                    coerced["params"] = call.get("params") or {}
                    prior_results.append(coerced)
                    FunctionCallOrchestrator._remember_job_sources(job, coerced.get("sources") or [])
                    if coerced.get("truncated"):
                        MessageRouter.tool_only_note(
                            chat_id=job.chat.id if job.chat else None,
                            content=coerced.get(
                                "truncation_reason", "Result truncated for size"
                            ),
                            role="caller",
                            job=job,
                            metadata={"include_in_context": False, "kind": "truncation_notice"},
                        )
                    MessageRouter.tool_only_note(
                        chat_id=job.chat.id if job.chat else None,
                        content=f"Function result: {FunctionCallOrchestrator._summarize_result_for_log(result, context_summary=coerced.get('context_summary'), truncated=coerced.get('truncated', False), truncation_reason=coerced.get('truncation_reason', ''))}",
                        role="runner",
                        job=job,
                        call_id=result.call_id,
                        metadata={"include_in_context": True, "kind": "function_result_summary"},
                    )
                    JobService.heartbeat(job)
                    continue

                if decision.get("done"):
                    break

        except Exception as exc:  # pragma: no cover
            logger.exception("Function caller resume crashed")
            err = f"Function Caller error: {exc}"
            MessageRouter.tool_only_note(
                chat_id=job.chat.id if job and job.chat else None,
                content=err,
                role="caller",
                job=job,
            )
            MessageRouter.frontman_update(
                chat_id=job.chat.id if job and job.chat else None,
                content="The job failed due to an internal error. Please try again.",
                job=job,
                message_type="user_visible",
            )
            JobService.mark_status(job, Job.STATUS_FAILED, error_summary=str(exc))
            return "Job failed."

        summary = decision.get("summary") or "No actions taken."
        if prior_results and not summary:
            summary = "Completed."

        # Clear pending state when finished.
        job.metadata.pop("pending_state", None)
        job.save(update_fields=["metadata", "updated_at"])
        return summary
