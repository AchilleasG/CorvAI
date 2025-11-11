from __future__ import annotations

import json
import logging
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from openai import OpenAI

from Corv.config import settings
from chat.models import Chat, ChatMessage
from mcp.models import (
    FunctionExecutionLog,
    MCPModule,
    ModuleFunction,
    ModuleFunctionErrorPolicy,
    ModuleFunctionParameter,
    TaskPlan,
)


@dataclass
class TaskManagerOutcome:
    status: str
    frontman_context: Optional[str] = None
    missing_information: Optional[List[Dict[str, Any]]] = None
    function_calls: Optional[List[Dict[str, Any]]] = None
    execution_results: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


class ModuleManifestBuilder:
    """Serialize MCP modules/functions so the task manager AI can reason about them."""

    @staticmethod
    def build_manifest() -> List[Dict[str, Any]]:
        modules = (
            MCPModule.objects.prefetch_related(
                "functions__parameters",
                "functions__error_policies",
            )
            .order_by("name")
            .all()
        )

        manifest: List[Dict[str, Any]] = []
        for module in modules:
            module_entry: Dict[str, Any] = {
                "module": module.slug,
                "name": module.name,
                "description": module.description,
                "functions": [],
            }
            for function in module.functions.all().order_by("name"):
                module_entry["functions"].append(
                    {
                        "function": function.slug,
                        "name": function.name,
                        "description": function.description,
                        "knowledge_requirements": function.knowledge_requirements,
                        "result_description": function.result_description,
                        "parameters": [
                            {
                                "name": param.name,
                                "type": param.data_type,
                                "required": param.required,
                                "description": param.description,
                                "default": param.default_value,
                                "allowed_values": param.allowed_values,
                                "example": param.example,
                            }
                            for param in function.parameters.all().order_by("name")
                        ],
                        "error_policies": [
                            {
                                "code": policy.code,
                                "description": policy.description,
                                "handling_notes": policy.handling_notes,
                                "severity": policy.severity,
                            }
                            for policy in function.error_policies.all().order_by("code")
                        ],
                    }
                )
            manifest.append(module_entry)
        return manifest


class FunctionExecutionError(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


logger = logging.getLogger(__name__)


class FunctionExecutor:
    """Registry-backed function dispatcher."""

    _registry: Dict[str, Callable[..., Dict[str, Any]]] = {}

    @classmethod
    def register(cls, module_slug: str, function_slug: str):
        def decorator(func: Callable[..., Dict[str, Any]]):
            cls._registry[f"{module_slug}.{function_slug}"] = func
            return func

        return decorator

    @classmethod
    def execute(
        cls,
        chat: Chat,
        function: ModuleFunction,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        key = f"{function.module.slug}.{function.slug}"
        handler = cls._registry.get(key)
        if not handler:
            raise FunctionExecutionError("NOT_IMPLEMENTED", f"No executor registered for {key}")

        # Validate required params
        missing = [
            p.name
            for p in function.parameters.all()
            if p.required and (p.name not in parameters or parameters[p.name] in (None, ""))
        ]
        if missing:
            raise FunctionExecutionError(
                "MISSING_PARAMETERS",
                f"Missing parameters: {', '.join(missing)}",
                {"missing": missing},
            )

        logger.info(
            "Executing MCP function",
            extra={
                "mcp_function": key,
                "chat_id": str(chat.id),
                "parameters": parameters,
            },
        )
        result = handler(chat=chat, **parameters)
        logger.info(
            "Finished MCP function",
            extra={
                "mcp_function": key,
                "chat_id": str(chat.id),
                "result": result,
            },
        )
        return result


def _tomorrow_iso() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


@FunctionExecutor.register("calendar", "add_event")
def _dummy_add_event(
    *,
    chat: Chat,
    title: str,
    date: str,
    time: str,
    duration_minutes: int | str = 60,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Simple demo calendar executor."""

    if isinstance(duration_minutes, str) and duration_minutes.isdigit():
        duration_minutes = int(duration_minutes)

    if date == _tomorrow_iso() and time == "17:00":
        raise FunctionExecutionError(
            "EVENT_CONFLICT",
            "Event already exists at that slot: band practice",
            {"conflict_with": "Band practice", "existing_time": time},
        )

    return {
        "status": "created",
        "title": title,
        "date": date,
        "time": time,
        "duration_minutes": duration_minutes,
        "notes": notes,
    }


@FunctionExecutor.register("dummy_ops", "check_name")
def _dummy_check_name(*, chat: Chat, name: str) -> Dict[str, Any]:
    """Validate a name and fail when it starts with 'A'."""
    if not name:
        raise FunctionExecutionError(
            "NAME_INVALID",
            "Name cannot be empty.",
            {"invalid_value": name},
        )

    if name.strip().lower().startswith("a"):
        raise FunctionExecutionError(
            "NAME_INVALID",
            "Names starting with the letter A are not allowed.",
            {"invalid_value": name},
        )

    return {
        "status": "ok",
        "accepted_name": name,
        "message": f"Name {name} accepted.",
    }


logger = logging.getLogger(__name__)


class TaskManagerAI:
    client = OpenAI(api_key=settings.openai_key)

    @classmethod
    def generate_plan(
        cls,
        chat: Chat,
        manifest: List[Dict[str, Any]],
        pending_missing: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        messages = ChatMessage.objects.filter(chat=chat).order_by("created_at")
        transcript = "\n".join(f"{m.role}: {m.text}" for m in messages)
        manifest_json = json.dumps(manifest, indent=2)
        pending_json = json.dumps(pending_missing or [], indent=2)

        system_prompt = (
            "You are Corv's Task Manager AI. You orchestrate modules and functions, "
            "identify what information is needed, and emit JSON plans."
        )
        user_prompt = f"""
Chat Transcript:\n{transcript}\n\nAvailable Modules Manifest:\n{manifest_json}\n\nOutstanding Missing Info From Previous Plan (if any):\n{pending_json}\n\nRespond strictly in JSON with keys: status [needs_info|ready|idle], reasoning, missing_information (list of objects with parameter, question, notes, suggested_answer), function_calls (list with module, function, parameters dict), and comments (optional).
"""
        user_prompt = user_prompt.strip() + "\n\nReturn ONLY raw JSON (no Markdown, no prose)."

        resp = cls.client.responses.create(
            model="gpt-5",
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                },
            ],
        )

        raw_output = getattr(resp, "output_text", None)
        if not raw_output:
            raise RuntimeError("Task manager returned empty output")

        try:
            return json.loads(raw_output)
        except (json.JSONDecodeError, AttributeError) as exc:
            logger.error(
                "Task manager returned invalid JSON",
                extra={
                    "chat_id": str(chat.id),
                    "raw_output": raw_output,
                },
            )
            raise RuntimeError("Task manager returned invalid JSON") from exc


class TaskManagerService:
    ACTION_TRIGGER = "action-prompt"

    @classmethod
    def get_or_create_plan(cls, chat: Chat) -> TaskPlan:
        plan, _ = TaskPlan.objects.get_or_create(chat=chat)
        return plan

    @classmethod
    def has_pending_plan(cls, chat: Chat) -> bool:
        plan = TaskPlan.objects.filter(chat=chat).order_by("-updated_at").first()
        return bool(plan and plan.status == "awaiting_info")

    @classmethod
    def process_chat(cls, chat: Chat) -> TaskManagerOutcome:
        plan_record = cls.get_or_create_plan(chat)
        manifest = ModuleManifestBuilder.build_manifest()
        ai_plan = TaskManagerAI.generate_plan(
            chat=chat,
            manifest=manifest,
            pending_missing=plan_record.missing_information,
        )

        plan_record.plan = ai_plan
        plan_record.missing_information = ai_plan.get("missing_information") or []
        plan_record.save(update_fields=["plan", "missing_information", "updated_at"])

        status = (ai_plan.get("status") or "idle").lower()
        if status == "needs_info":
            plan_record.status = "awaiting_info"
            plan_record.save(update_fields=["status", "updated_at"])
            context = cls._build_missing_info_prompt(plan_record.missing_information)
            return TaskManagerOutcome(
                status="awaiting_info",
                frontman_context=context,
                missing_information=plan_record.missing_information,
            )

        if status == "ready":
            return cls._execute_plan(chat, plan_record, ai_plan)

        plan_record.status = "idle"
        plan_record.save(update_fields=["status", "updated_at"])
        return TaskManagerOutcome(status="idle", frontman_context=None)

    @classmethod
    def _build_missing_info_prompt(cls, missing_items: List[Dict[str, Any]]) -> str:
        lines = [
            "Task manager still needs more info. Ask the user for the following details to keep work moving:"
        ]
        for item in missing_items:
            param = item.get("parameter")
            question = item.get("question")
            notes = item.get("notes")
            line = f"- {param}: {question or 'Politely ask for this value.'}"
            if notes:
                line += f" (Notes: {notes})"
            lines.append(line)
        lines.append("Do not say 'action-prompt' in this response.")
        return "\n".join(lines)

    @classmethod
    def _execute_plan(
        cls,
        chat: Chat,
        plan_record: TaskPlan,
        ai_plan: Dict[str, Any],
    ) -> TaskManagerOutcome:
        function_calls = ai_plan.get("function_calls") or []
        results: List[Dict[str, Any]] = []

        plan_record.status = "running"
        plan_record.save(update_fields=["status", "updated_at"])

        for call in function_calls:
            module_slug = call.get("module")
            function_slug = call.get("function")
            parameters = call.get("parameters") or {}

            function = ModuleFunction.objects.filter(
                module__slug=module_slug,
                slug=function_slug,
            ).first()
            if not function:
                plan_record.status = "error"
                plan_record.last_error = f"Missing function {module_slug}.{function_slug}"
                plan_record.save(update_fields=["status", "last_error", "updated_at"])
                return TaskManagerOutcome(
                    status="error",
                    error=f"Unknown function {module_slug}.{function_slug}",
                    frontman_context="I could not locate the implementation for that function.",
                )

            try:
                with transaction.atomic():
                    result = FunctionExecutor.execute(chat=chat, function=function, parameters=parameters)
                    FunctionExecutionLog.objects.create(
                        chat=chat,
                        function=function,
                        status="success",
                        request_payload=parameters,
                        response_payload=result,
                    )
                    logger.info(
                        "MCP function executed | chat=%s | function=%s | params=%s | result=%s",
                        chat.id,
                        f"{module_slug}.{function_slug}",
                        json.dumps(parameters),
                        json.dumps(result),
                    )
                    results.append({
                        "function": f"{module_slug}.{function_slug}",
                        "status": "success",
                        "result": result,
                    })
            except FunctionExecutionError as err:
                handling_notes = cls._lookup_handling_notes(function, err.code)
                FunctionExecutionLog.objects.create(
                    chat=chat,
                    function=function,
                    status="error",
                    request_payload=parameters,
                    response_payload={"message": str(err), "details": err.details},
                    error_code=err.code,
                )
                logger.warning(
                    "MCP function failed | chat=%s | function=%s | params=%s | error_code=%s | error=%s | details=%s",
                    chat.id,
                    f"{module_slug}.{function_slug}",
                    json.dumps(parameters),
                    err.code,
                    str(err),
                    json.dumps(err.details),
                )
                plan_record.status = "awaiting_info"
                plan_record.missing_information = [{
                    "parameter": err.code,
                    "question": handling_notes or str(err),
                    "notes": err.details,
                }]
                plan_record.last_error = str(err)
                plan_record.save(update_fields=["status", "missing_information", "last_error", "updated_at"])
                context = cls._build_error_prompt(function, err.code, str(err), handling_notes)
                return TaskManagerOutcome(
                    status="awaiting_decision",
                    frontman_context=context,
                    missing_information=plan_record.missing_information,
                    execution_results=results,
                    error=str(err),
                )

        plan_record.status = "completed"
        plan_record.resolved_at = timezone.now()
        plan_record.missing_information = []
        plan_record.save(update_fields=["status", "resolved_at", "missing_information", "updated_at"])

        success_context = cls._build_success_prompt(results)
        return TaskManagerOutcome(
            status="completed",
            frontman_context=success_context,
            execution_results=results,
        )

    @staticmethod
    def _lookup_handling_notes(function: ModuleFunction, code: str) -> Optional[str]:
        policy = function.error_policies.filter(code=code).first()
        return policy.handling_notes if policy else None

    @staticmethod
    def _build_error_prompt(function: ModuleFunction, code: str, message: str, handling_notes: Optional[str]) -> str:
        base = [
            f"Function {function.module.slug}.{function.slug} encountered error {code}: {message}.",
            "Translate the handling notes into a friendly set of options for the user.",
            "Never expose raw error codes unless it helps the user make a decision.",
            "Do not say 'action-prompt' in this response.",
        ]
        if handling_notes:
            base.insert(1, f"Handling notes: {handling_notes}")
        return "\n".join(base)

    @staticmethod
    def _build_success_prompt(results: List[Dict[str, Any]]) -> str:
        lines = [
            "Summarize the completed actions for the user in plain language.",
            "Explicitly state that the task is already done—no need to say you are going to do it.",
            "Highlight key parameters (date/time) and confirm completion.",
            "Do not say 'action-prompt' anywhere in the response.",
        ]
        for result in results:
            details = result.get("result") or {}
            lines.append(f"Action result: {json.dumps(details)}")
        return "\n".join(lines)
