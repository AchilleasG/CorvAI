from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from orchestration.models import (
    FrontmanPersona,
    Job,
    JobEvent,
    ToolFunction,
    ToolModule,
)
from orchestration.registry import FunctionRegistry
from orchestration.schemas import FunctionCallPayload, FunctionResultPayload, MessageEnvelope

logger = logging.getLogger(__name__)


class JobService:
    @staticmethod
    @transaction.atomic
    def create_job(
        *,
        chat=None,
        session_id: str = "",
        trace_id: Optional[str] = None,
        module: Optional[ToolModule] = None,
        user_visible_summary: str = "",
    ) -> Job:
        trace_id = trace_id or str(uuid.uuid4())
        job = Job.objects.create(
            chat=chat,
            session_id=session_id,
            trace_id=trace_id,
            module=module,
            status=Job.STATUS_PENDING,
            user_visible_summary=user_visible_summary,
            started_at=timezone.now(),
        )
        JobEvent.objects.create(
            job=job,
            role="frontman",
            event_type=JobEvent.EVENT_STATE,
            visibility=JobEvent.VISIBILITY_SYSTEM,
            message="Job created",
        )
        return job

    @staticmethod
    @transaction.atomic
    def append_event(
        job: Job,
        *,
        role: str,
        event_type: str,
        visibility: str,
        message: str = "",
        payload: Optional[Dict[str, Any]] = None,
        call_id: str = "",
    ) -> JobEvent:
        return JobEvent.objects.create(
            job=job,
            role=role,
            event_type=event_type,
            visibility=visibility,
            message=message,
            payload=payload or {},
            call_id=call_id,
        )

    @staticmethod
    @transaction.atomic
    def mark_status(job: Job, status: str, *, error_summary: str = "", progress: float | None = None):
        job.status = status
        if progress is not None:
            job.progress = progress
        if status in (Job.STATUS_COMPLETED, Job.STATUS_FAILED, Job.STATUS_CANCELED):
            job.finished_at = timezone.now()
        if error_summary:
            job.error_summary = error_summary
        job.save(update_fields=["status", "progress", "finished_at", "error_summary", "updated_at"])
        JobEvent.objects.create(
            job=job,
            role="caller",
            event_type=JobEvent.EVENT_STATE,
            visibility=JobEvent.VISIBILITY_SYSTEM,
            message=f"Job status -> {status}",
            payload={"error_summary": error_summary} if error_summary else {},
        )
        return job

    @staticmethod
    @transaction.atomic
    def request_cancel(job: Job, reason: str = ""):
        # Hard stop: mark canceled immediately and prevent further execution.
        job.cancel_requested = True
        job.status = Job.STATUS_CANCELED
        job.finished_at = timezone.now()
        job.save(update_fields=["cancel_requested", "status", "finished_at", "updated_at"])
        JobEvent.objects.create(
            job=job,
            role="frontman",
            event_type=JobEvent.EVENT_STATE,
            visibility=JobEvent.VISIBILITY_USER,
            message="Job canceled",
            payload={"reason": reason} if reason else {},
        )
        return job


class FunctionRunnerService:
    """
    Thin wrapper that resolves a function from the registry and executes it.
    """

    @staticmethod
    def run_function_call(
        payload: FunctionCallPayload,
        *,
        job: Optional[Job] = None,
    ) -> FunctionResultPayload:
        try:
            func = FunctionRegistry.resolve_callable(payload.function_id)
        except KeyError as exc:
            logger.exception("Function resolution failed for %s", payload.function_id)
            return FunctionResultPayload(
                trace_id=payload.trace_id,
                call_id=payload.call_id,
                status="error",
                error_summary=str(exc),
                job_id=str(job.id) if job else None,
            )

        if job and (job.cancel_requested or job.status == Job.STATUS_CANCELED):
            return FunctionResultPayload(
                trace_id=payload.trace_id,
                call_id=payload.call_id,
                status="error",
                error_summary="Job canceled before execution",
                job_id=str(job.id),
            )

        job_event_payload = {
            "function_id": payload.function_id,
            "params": payload.params,
        }

        if job:
            JobService.append_event(
                job,
                role="runner",
                event_type=JobEvent.EVENT_INFO,
                visibility=JobEvent.VISIBILITY_SYSTEM,
                message="Executing function",
                payload=job_event_payload,
                call_id=payload.call_id,
            )

        try:
            result = func(**payload.params) if payload.params else func()
            status = "ok"
            error_summary = None
        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("Function '%s' raised", payload.function_id)
            result = None
            status = "error"
            error_summary = str(exc)

        if job:
            JobService.append_event(
                job,
                role="runner",
                event_type=JobEvent.EVENT_INFO if status == "ok" else JobEvent.EVENT_ERROR,
                visibility=JobEvent.VISIBILITY_TOOL,
                message="Function completed" if status == "ok" else "Function error",
                payload={"result": result, "error_summary": error_summary},
                call_id=payload.call_id,
            )

        return FunctionResultPayload(
            trace_id=payload.trace_id,
            call_id=payload.call_id,
            status=status,
            data=result if status == "ok" else None,
            error_summary=error_summary,
            job_id=str(job.id) if job else None,
        )


class FunctionCallerService:
    """
    DB-backed helper to fetch modules/functions and track per-call planning.
    """

    @staticmethod
    def list_modules():
        return ToolModule.objects.all().order_by("name")

    @staticmethod
    def list_functions_for_module(module: ToolModule):
        return ToolFunction.objects.filter(module=module, deprecated=False).order_by("name")

    @staticmethod
    def build_call_payload(
        *,
        function: ToolFunction,
        params: Dict[str, Any],
        trace_id: Optional[str] = None,
        job: Optional[Job] = None,
        rationale: str | None = None,
        plan_step: str | None = None,
    ) -> FunctionCallPayload:
        call_id = str(uuid.uuid4())
        return FunctionCallPayload(
            trace_id=trace_id or (job.trace_id if job else str(uuid.uuid4())),
            call_id=call_id,
            function_id=function.manifest_id,
            params=params,
            rationale=rationale,
            plan_step=plan_step,
            job_id=str(job.id) if job else None,
        )

    @staticmethod
    def heartbeat(job: Job):
        # Simple heartbeat to keep jobs fresh; could be triggered by Caller loop.
        job.updated_at = timezone.now()
        job.save(update_fields=["updated_at"])
        return job


class ModuleDirectory:
    """
    Centralized access to modules and functions for Front Man and Function Caller.
    """

    @staticmethod
    def module_summaries():
        data = []
        for mod in ToolModule.objects.all().order_by("name"):
            count = ToolFunction.objects.filter(module=mod, deprecated=False).count()
            data.append(
                {
                    "slug": mod.slug,
                    "name": mod.name,
                    "description": mod.description,
                    "function_count": count,
                }
            )
        return data

    @staticmethod
    def function_catalog():
        """
        Return lightweight descriptors of all functions for the Function Caller.
        """
        out = []
        for func in (
            ToolFunction.objects.filter(deprecated=False)
            .select_related("module")
            .order_by("module__name", "name")
        ):
            out.append(
                {
                    "manifest_id": func.manifest_id,
                    "module": func.module.slug,
                    "name": func.name,
                    "description": func.description,
                    "params_schema": func.params_schema or {},
                    "module_caller_instructions": func.module.caller_instructions or "",
                }
            )
        return out

    @staticmethod
    def function_tool_specs():
        """
        Build OpenAI tool specs from ToolFunction manifests. Caller can use this
        to expose tools automatically; Runner resolves via registry.
        """
        specs = []
        for func in ToolFunction.objects.filter(deprecated=False).select_related("module"):
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": func.manifest_id,
                        "description": func.description,
                        "parameters": func.params_schema or {"type": "object"},
                    },
                    # extra metadata could live in func.tags
                }
            )
        return specs


class PersonaService:
    """
    Accessor for Front Man persona instructions.
    """

    @staticmethod
    def get_persona(slug: Optional[str] = None) -> Optional[FrontmanPersona]:
        qs = FrontmanPersona.objects.all()
        if slug:
            try:
                return qs.get(slug=slug)
            except FrontmanPersona.DoesNotExist:
                return None
        active = qs.filter(is_active=True).order_by("-updated_at", "-created_at").first()
        if active:
            return active
        return qs.order_by("-created_at").first()

    @staticmethod
    def build_persona_prompt(slug: Optional[str] = None) -> str:
        persona = PersonaService.get_persona(slug)
        if not persona:
            return (
                "You are Corv's Front Man. Be personable, concise, and keep the user "
                "informed about background work. Use the available modules when helpful."
            )
        base = persona.instructions
        if persona.postamble:
            base = f"{base}\n\n{persona.postamble}"
        return base
