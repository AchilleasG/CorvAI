from __future__ import annotations

import json
from json import JSONDecoder
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from Corv.config import settings
from orchestration.services import ModuleDirectory, FunctionRunnerService, JobService, ModelConfigService, UsageService
from orchestration.models import Job
from orchestration.schemas import FunctionCallPayload
from orchestration.message_router import MessageRouter

logger = logging.getLogger(__name__)


class FunctionCallOrchestrator:
    """
    Iterative Function Caller that plans and executes tool calls using manifests from the DB.
    """

    client = OpenAI(api_key=settings.openai_key)
    MAX_RESULT_CHARS = 6000  # guardrail to avoid blowing out prompt/context

    @staticmethod
    def _plan_next_action(
        *,
        user_request: str,
        tool_catalog: List[Dict[str, Any]],
        prior_results: List[Dict[str, Any]],
        model: str = "gpt-5.2",
        cache_mode: str = "off",
        job: Optional[Job] = None,
        chat_id: Optional[str] = None,
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
            calendar_defaults.append(f"Use calendar_id='{settings.google_calendar_default_id}' if none provided.")
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
        results_text = json.dumps(prior_results, ensure_ascii=False)
        instructions = (
            "You are the Function Caller. Decide one step at a time whether to call a function, ask the user, or finish.\n"
            "Module hints to respect when planning:\n"
            f"{module_hints_text}\n"
            "Module defaults:\n"
            f"{defaults_text}\n"
            "Functions available:\n"
            f"{tools_text}\n\n"
            "Always return JSON: "
            '{"done":bool,'
            '"call": {"function_id": "...", "params": {...}} or null,'
            '"ask_user": "question text" or null,'
            '"summary": "short summary"}\n'
            "Rules:\n"
            "- Only use function_ids from the catalog.\n"
            "- If you need output from a previous call, it is in prior_results.\n"
            "- If you need user input, set ask_user and done=true.\n"
            "- Do NOT fabricate data; only summarize actual function results in prior_results.\n"
            "- If you lack the data, propose the function call to get it (do not mark done with a fabricated summary).\n"
            "- If no function needed, set done=true and summary."
        )

        input_seq = [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": instructions}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": f"User request: {user_request}"}],
            },
            {
                "role": "system",
                "content": [{"type": "input_text", "text": f"Prior results: {results_text}"}],
            },
        ]

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
            resp_kwargs["prompt_cache_key"] = f"caller-v1-{catalog_sig}"
        resp = FunctionCallOrchestrator.client.responses.create(**resp_kwargs)
        if getattr(resp, "usage", None):
            UsageService.log_usage(
                source="caller_plan",
                model=model,
                cache_mode=cache_mode,
                usage=getattr(resp, "usage", {}),
                prompt_cache_key=resp_kwargs.get("prompt_cache_key", ""),
                job=job,
            )
        raw = getattr(resp, "output_text", "{}") or "{}"
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
                    first_obj = obj  # prefer the first well-formed JSON object (the decision)
                idx = end
            except json.JSONDecodeError:
                # Move forward to next brace and try again
                next_brace = text.find("{", idx + 1)
                if next_brace == -1:
                    break
                idx = next_brace
                continue
        if isinstance(first_obj, dict):
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
    def _coerce_result_payload(result: FunctionResultPayload) -> Dict[str, Any]:
        """
        Ensure the stored result is bounded so the next prompt doesn't explode.
        """
        data = result.data
        coerced = {
            "function_id": result.call_id,
            "status": result.status,
            "data": data,
            "error": result.error_summary,
        }
        if data is None:
            coerced["data"] = None
            coerced["truncated"] = False
            return coerced

        try:
            import json

            serialized = json.dumps(data, ensure_ascii=False)
            if len(serialized) > FunctionCallOrchestrator.MAX_RESULT_CHARS:
                coerced["data"] = None
                coerced["truncated"] = True
                coerced["truncation_reason"] = (
                    f"Result too large ({len(serialized)} chars). Ask for narrower scope or filters."
                )
        except Exception:
            coerced["truncated"] = False
        return coerced

    @staticmethod
    def run(chat_context: Dict[str, Any], job: Job, max_steps: int = 5) -> str:
        tool_catalog = ModuleDirectory.function_catalog()
        # Build a brief recent-context string (last 10 messages).
        messages = chat_context.get("messages") or []
        recent = messages[-10:] if len(messages) > 10 else messages
        ctx_lines = []
        for m in recent:
            prefix = "User" if m.role == "user" else "Assistant" if m.role == "assistant" else "Tool"
            ts = f"[{m.created_at.isoformat()}] " if getattr(m, "created_at", None) else ""
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
                    )
                    result = FunctionRunnerService.run_function_call(payload, job=job)
                    coerced = FunctionCallOrchestrator._coerce_result_payload(result)
                    coerced["function_id"] = call["function_id"]
                    coerced["params"] = call.get("params") or {}
                    prior_results.append(coerced)
                    if coerced.get("truncated"):
                        MessageRouter.tool_only_note(
                            chat_id=job.chat.id if job.chat else None,
                            content=coerced.get("truncation_reason", "Result truncated for size"),
                            role="caller",
                            job=job,
                        )
                    MessageRouter.tool_only_note(
                        chat_id=job.chat.id if job.chat else None,
                        content=f"Function result: {result.model_dump()}",
                        role="runner",
                        job=job,
                        call_id=result.call_id,
                    )
                    job.updated_at = job.updated_at  # no-op placeholder to avoid stale writes
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
            summary = decision.get("summary") or "Completed calls."
            # Append concise list of results for transparency.
            summary += "\n" + "\n".join(
                f"- {r['function_id']}: {r['status']}"
                for r in prior_results
            )
        else:
            summary = decision.get("summary") or "No actions taken."

        return summary

    @staticmethod
    def resume(chat_context: Dict[str, Any], job: Job, user_response: str, max_steps: int = 5) -> str:
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
            prefix = "User" if m.role == "user" else "Assistant" if m.role == "assistant" else "Tool"
            ts = f"[{m.created_at.isoformat()}] " if getattr(m, "created_at", None) else ""
            ctx_lines.append(f"{prefix}: {ts}{m.text}")
        ctx_lines.append(f"User (new): {user_response}")
        user_request = "\n".join(ctx_lines)
        tool_catalog = ModuleDirectory.function_catalog()

        try:
            model_name = ModelConfigService.get_caller_model()
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
                    )
                    result = FunctionRunnerService.run_function_call(payload, job=job)
                    coerced = FunctionCallOrchestrator._coerce_result_payload(result)
                    coerced["function_id"] = call["function_id"]
                    coerced["params"] = call.get("params") or {}
                    prior_results.append(coerced)
                    if coerced.get("truncated"):
                        MessageRouter.tool_only_note(
                            chat_id=job.chat.id if job.chat else None,
                            content=coerced.get("truncation_reason", "Result truncated for size"),
                            role="caller",
                            job=job,
                        )
                    MessageRouter.tool_only_note(
                        chat_id=job.chat.id if job.chat else None,
                        content=f"Function result: {result.model_dump()}",
                        role="runner",
                        job=job,
                        call_id=result.call_id,
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
        if prior_results:
            summary += "\n" + "\n".join(f"- {r['function_id']}: {r['status']}" for r in prior_results)

        # Clear pending state when finished.
        job.metadata.pop("pending_state", None)
        job.save(update_fields=["metadata", "updated_at"])
        return summary
