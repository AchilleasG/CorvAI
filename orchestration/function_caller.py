from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from openai import OpenAI

from Corv.config import settings
from orchestration.services import ModuleDirectory, FunctionRunnerService, JobService
from orchestration.models import Job
from orchestration.schemas import FunctionCallPayload
from orchestration.message_router import MessageRouter


class FunctionCallOrchestrator:
    """
    Iterative Function Caller that plans and executes tool calls using manifests from the DB.
    """

    client = OpenAI(api_key=settings.openai_key)

    @staticmethod
    def _plan_next_action(
        *,
        user_request: str,
        tool_catalog: List[Dict[str, Any]],
        prior_results: List[Dict[str, Any]],
        model: str = "gpt-5",
    ) -> Dict[str, Any]:
        """
        Ask the model to decide the next function call (or finish/ask user) with strict JSON.
        """
        tools_text = "\n".join(
            f"- {t['manifest_id']} (module: {t['module']}): {t['description']} | params: {list((t.get('params_schema') or {}).get('properties', {}).keys())}"
            for t in tool_catalog
        )
        results_text = json.dumps(prior_results, ensure_ascii=False)
        instructions = (
            "You are the Function Caller. Decide one step at a time whether to call a function, ask the user, or finish.\n"
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

        resp = FunctionCallOrchestrator.client.responses.create(
            model=model,
            input=input_seq,
            tools=[],  # planning only
            text={"format": {"type": "text"}},
        )
        return json.loads(getattr(resp, "output_text", "{}"))

    @staticmethod
    def run(chat_context: Dict[str, Any], job: Job, max_steps: int = 5) -> str:
        tool_catalog = ModuleDirectory.function_catalog()
        # Use the latest user message as the request.
        messages = chat_context.get("messages") or []
        user_msgs = [m for m in messages if m.role == "user"]
        user_request = user_msgs[-1].text if user_msgs else ""

        prior_results: List[Dict[str, Any]] = []

        for step in range(max_steps):
            decision = FunctionCallOrchestrator._plan_next_action(
                user_request=user_request,
                tool_catalog=tool_catalog,
                prior_results=prior_results,
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
                result = FunctionRunnerService.run_function_call(payload, job=job)
                prior_results.append(
                    {
                        "function_id": call["function_id"],
                        "params": call.get("params") or {},
                        "status": result.status,
                        "data": result.data,
                        "error": result.error_summary,
                    }
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
        user_request = f"{base_request}\nAdditional user info: {user_response}"
        tool_catalog = ModuleDirectory.function_catalog()

        for step in range(max_steps):
            decision = FunctionCallOrchestrator._plan_next_action(
                user_request=user_request,
                tool_catalog=tool_catalog,
                prior_results=prior_results,
            )

            if decision.get("ask_user"):
                MessageRouter.frontman_update(
                    chat_id=job.chat.id if job.chat else None,
                    content=decision["ask_user"],
                    job=job,
                    message_type="user_visible",
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
                result = FunctionRunnerService.run_function_call(payload, job=job)
                prior_results.append(
                    {
                        "function_id": call["function_id"],
                        "params": call.get("params") or {},
                        "status": result.status,
                        "data": result.data,
                        "error": result.error_summary,
                    }
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

        summary = decision.get("summary") or "No actions taken."
        if prior_results:
            summary += "\n" + "\n".join(f"- {r['function_id']}: {r['status']}" for r in prior_results)

        # Clear pending state when finished.
        job.metadata.pop("pending_state", None)
        job.save(update_fields=["metadata", "updated_at"])
        return summary
