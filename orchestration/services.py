from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional, List, Iterable, Tuple
from datetime import datetime, timedelta

from openai import OpenAI
from django.db import transaction, models
from django.utils import timezone

from orchestration.models import (
    FrontmanPersona,
    Job,
    JobEvent,
    ToolFunction,
    ToolModule,
    OrchestrationSetting,
    UsageEvent,
    UserProfile,
    UserNote,
)
from orchestration.registry import FunctionRegistry
from orchestration.schemas import (
    FunctionCallPayload,
    FunctionResultPayload,
    MessageEnvelope,
)
from Corv.config import settings

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
    def mark_status(
        job: Job, status: str, *, error_summary: str = "", progress: float | None = None
    ):
        job.status = status
        if progress is not None:
            job.progress = progress
        if status in (Job.STATUS_COMPLETED, Job.STATUS_FAILED, Job.STATUS_CANCELED):
            job.finished_at = timezone.now()
        if error_summary:
            job.error_summary = error_summary
        job.save(
            update_fields=[
                "status",
                "progress",
                "finished_at",
                "error_summary",
                "updated_at",
            ]
        )
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
        job.save(
            update_fields=["cancel_requested", "status", "finished_at", "updated_at"]
        )
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
                event_type=(
                    JobEvent.EVENT_INFO if status == "ok" else JobEvent.EVENT_ERROR
                ),
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
        return ToolFunction.objects.filter(module=module, deprecated=False).order_by(
            "name"
        )

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
        for func in ToolFunction.objects.filter(deprecated=False).select_related(
            "module"
        ):
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


class UserInfoService:
    """
    Helpers for core and circumstantial user info with embeddings.
    """

    client = OpenAI(api_key=settings.openai_key)
    DEFAULT_USER_ID = "default"
    DEFAULT_EMBED_MODEL = "text-embedding-3-small"

    @staticmethod
    def _normalize_user_id(user_id: Optional[str] = None) -> str:
        return user_id or UserInfoService.DEFAULT_USER_ID

    @staticmethod
    def _canonicalize(text: str) -> str:
        return " ".join(text.strip().split()).lower()

    @staticmethod
    def _embed_text(text: str, model: Optional[str] = None) -> Optional[list]:
        if not text:
            return None
        model_name = model or ModelConfigService.get_user_info_embedding_model()
        resp = UserInfoService.client.embeddings.create(model=model_name, input=[text])
        if getattr(resp, "data", None):
            return resp.data[0].embedding  # type: ignore[attr-defined]
        return None

    @staticmethod
    def get_core_profile(user_id: Optional[str] = None) -> Optional[UserProfile]:
        uid = UserInfoService._normalize_user_id(user_id)
        return UserProfile.objects.filter(user_id=uid).first()

    @staticmethod
    def set_core_profile(text: str, user_id: Optional[str] = None) -> UserProfile:
        uid = UserInfoService._normalize_user_id(user_id)
        profile, _ = UserProfile.objects.update_or_create(
            user_id=uid,
            defaults={"core_text": text},
        )
        return profile

    @staticmethod
    def append_core_profile(
        text: str, user_id: Optional[str] = None, separator: str = "\n"
    ) -> UserProfile:
        uid = UserInfoService._normalize_user_id(user_id)
        profile, _ = UserProfile.objects.get_or_create(
            user_id=uid, defaults={"core_text": ""}
        )
        base = profile.core_text or ""
        sep = separator if base and separator is not None else ""
        profile.core_text = f"{base}{sep}{text}".strip()
        profile.save(update_fields=["core_text", "updated_at"])
        return profile

    @staticmethod
    def delete_core_profile(user_id: Optional[str] = None):
        uid = UserInfoService._normalize_user_id(user_id)
        UserProfile.objects.filter(user_id=uid).delete()

    @staticmethod
    def format_core_profile_block(user_id: Optional[str] = None) -> str:
        profile = UserInfoService.get_core_profile(user_id)
        if not profile or not profile.core_text:
            return ""
        return f"User profile:\n{profile.core_text}"

    @staticmethod
    def add_note(
        *,
        content: str,
        user_id: Optional[str] = None,
        source: str = "",
        tags: Optional[list] = None,
        canonicalize: bool = True,
        model: Optional[str] = None,
    ) -> UserNote:
        uid = UserInfoService._normalize_user_id(user_id)
        canonical = UserInfoService._canonicalize(content) if canonicalize else content
        embedding = UserInfoService._embed_text(canonical or content, model=model)
        note = UserNote.objects.create(
            user_id=uid,
            content_raw=content,
            content_canonical=canonical or "",
            embedding=embedding,
            source=source or "",
            tags=tags or [],
        )
        return note

    @staticmethod
    def update_note(
        note_id: str,
        *,
        content: str,
        user_id: Optional[str] = None,
        source: Optional[str] = None,
        tags: Optional[list] = None,
        canonicalize: bool = True,
        model: Optional[str] = None,
    ) -> UserNote:
        uid = UserInfoService._normalize_user_id(user_id)
        note = UserNote.objects.filter(
            id=note_id, user_id=uid, deleted_at__isnull=True
        ).first()
        if not note:
            raise ValueError("Note not found")
        canonical = UserInfoService._canonicalize(content) if canonicalize else content
        embedding = UserInfoService._embed_text(canonical or content, model=model)
        note.content_raw = content
        note.content_canonical = canonical or ""
        note.embedding = embedding
        if source is not None:
            note.source = source
        if tags is not None:
            note.tags = tags
        note.save(
            update_fields=[
                "content_raw",
                "content_canonical",
                "embedding",
                "source",
                "tags",
                "updated_at",
            ]
        )
        return note

    @staticmethod
    def delete_note(note_id: str, *, user_id: Optional[str] = None):
        uid = UserInfoService._normalize_user_id(user_id)
        note = UserNote.objects.filter(
            id=note_id, user_id=uid, deleted_at__isnull=True
        ).first()
        if not note:
            return
        note.deleted_at = timezone.now()
        note.save(update_fields=["deleted_at", "updated_at"])

    @staticmethod
    def search_notes(
        query: str,
        *,
        user_id: Optional[str] = None,
        limit: int = 5,
        source: Optional[str] = None,
        tag: Optional[str] = None,
        model: Optional[str] = None,
    ) -> list:
        uid = UserInfoService._normalize_user_id(user_id)
        canonical_query = UserInfoService._canonicalize(query)
        embedding = UserInfoService._embed_text(canonical_query, model=model)
        if not embedding:
            return []
        from pgvector.django import (
            CosineDistance,
        )  # local import to avoid module load issues

        qs = UserNote.objects.filter(
            user_id=uid, deleted_at__isnull=True, embedding__isnull=False
        )
        if source:
            qs = qs.filter(source=source)
        if tag:
            qs = qs.filter(tags__contains=[tag])
        qs = qs.annotate(distance=CosineDistance("embedding", embedding)).order_by(
            "distance"
        )[:limit]
        out = []
        for n in qs:
            out.append(
                {
                    "id": str(n.id),
                    "user_id": n.user_id,
                    "content": n.content_raw,
                    "content_canonical": n.content_canonical,
                    "source": n.source,
                    "tags": n.tags,
                    "created_at": n.created_at,
                    "distance": getattr(n, "distance", None),
                }
            )
        return out


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
        active = (
            qs.filter(is_active=True).order_by("-updated_at", "-created_at").first()
        )
        if active:
            return active
        return qs.order_by("-created_at").first()

    @staticmethod
    def build_persona_prompt(slug: Optional[str] = None) -> str:
        persona = PersonaService.get_persona(slug)
        if not persona:
            base = (
                "You are Corv's Front Man. Be personable, concise, and keep the user "
                "informed about background work. Use the available modules when helpful."
            )
        else:
            base = persona.instructions
            if persona.postamble:
                base = f"{base}\n\n{persona.postamble}"
        profile_block = UserInfoService.format_core_profile_block()
        if profile_block:
            base = f"{base}\n\n{profile_block}"
        return base


class ModelConfigService:
    """
    Accessor for dynamic model selection stored in OrchestrationSetting.
    """

    DEFAULT_FRONTMAN_MODEL = "gpt-5-mini"
    DEFAULT_CALLER_MODEL = "gpt-5-mini"
    DEFAULT_CACHE_MODE = "off"
    DEFAULT_PRICING_JSON = "{}"
    DEFAULT_USER_INFO_EMBED_MODEL = "text-embedding-3-small"
    DEFAULT_MAX_FUNCTION_RESULT_CHARS = 6000

    @staticmethod
    def get_setting(key: str, default: str) -> str:
        try:
            setting = OrchestrationSetting.objects.get(key=key)
            return setting.value or default
        except OrchestrationSetting.DoesNotExist:
            return default

    @staticmethod
    def set_setting(key: str, value: str):
        OrchestrationSetting.objects.update_or_create(
            key=key, defaults={"value": value}
        )

    @staticmethod
    def get_frontman_model() -> str:
        return ModelConfigService.get_setting(
            "frontman_model", ModelConfigService.DEFAULT_FRONTMAN_MODEL
        )

    @staticmethod
    def get_caller_model() -> str:
        return ModelConfigService.get_setting(
            "caller_model", ModelConfigService.DEFAULT_CALLER_MODEL
        )

    @staticmethod
    def get_cache_mode() -> str:
        """
        Returns 'off', 'frontman', 'caller', or 'all'.
        """
        return ModelConfigService.get_setting(
            "cache_mode", ModelConfigService.DEFAULT_CACHE_MODE
        ).lower()

    @staticmethod
    def get_pricing() -> dict:
        """
        Returns a dict of {model: {prompt_per_1k: float, completion_per_1k: float}} from setting 'model_pricing'.
        """
        import json

        raw = ModelConfigService.get_setting(
            "model_pricing", ModelConfigService.DEFAULT_PRICING_JSON
        )
        try:
            data = json.loads(raw) if raw else {}
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
        return {}

    @staticmethod
    def get_user_info_embedding_model() -> str:
        return ModelConfigService.get_setting(
            "user_info_embedding_model",
            ModelConfigService.DEFAULT_USER_INFO_EMBED_MODEL,
        )

    @staticmethod
    def get_max_function_result_chars() -> int:
        try:
            raw = ModelConfigService.get_setting(
                "max_function_result_chars",
                str(ModelConfigService.DEFAULT_MAX_FUNCTION_RESULT_CHARS),
            )
            return int(raw)
        except Exception:
            return ModelConfigService.DEFAULT_MAX_FUNCTION_RESULT_CHARS


class SoftEventService:
    """
    Helpers for soft events (flexible tasks) and their planned slots.
    """

    logger = logging.getLogger(__name__)

    @staticmethod
    def _parse_dt(val: Any) -> Optional[datetime]:
        if val is None:
            return None
        if isinstance(val, datetime):
            if timezone.is_naive(val):
                return timezone.make_aware(val, timezone=timezone.utc)
            return val
        try:
            parsed = datetime.fromisoformat(str(val))
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone=timezone.utc)
            return parsed
        except Exception:
            return None

    @staticmethod
    def list_soft_events_for_window(
        start: datetime, end: datetime
    ) -> List["SoftEvent"]:
        from orchestration.models import SoftEvent  # local import to avoid cycles

        return list(
            SoftEvent.objects.filter(status=SoftEvent.STATUS_ACTIVE).filter(
                models.Q(soft_deadline__isnull=True)
                | models.Q(soft_deadline__gte=start),
                models.Q(hard_deadline__isnull=True)
                | models.Q(hard_deadline__gte=start),
            )
        )

    @staticmethod
    def list_slots_for_window(start: datetime, end: datetime) -> List["SoftEventSlot"]:
        from orchestration.models import SoftEventSlot

        return list(
            SoftEventSlot.objects.filter(start_at__lt=end, end_at__gt=start).exclude(
                status=SoftEventSlot.STATUS_CANCELED
            )
        )

    @staticmethod
    def due_slots(
        now: datetime | None = None, horizon_minutes: int = 10
    ) -> List["SoftEventSlot"]:
        from orchestration.models import SoftEventSlot

        now = now or timezone.now()
        horizon = now + timedelta(minutes=horizon_minutes)
        return list(
            SoftEventSlot.objects.filter(
                status=SoftEventSlot.STATUS_PLANNED,
                start_at__gte=now,
                start_at__lte=horizon,
            )
        )

    @staticmethod
    def _build_soft_event_call_prompt(soft_event: "SoftEvent", slot: "SoftEventSlot") -> str:
        description = (soft_event.description or "").strip()
        goal = f"Time to do: {soft_event.title}."
        if description:
            goal = f"{goal} {description}"
        notes = (soft_event.notes or "").strip()
        if notes:
            goal = f"{goal} Notes: {notes}"
        start_at = slot.start_at.isoformat()
        end_at = slot.end_at.isoformat()
        return (
            "Reminder task for a soft event.\n"
            f"soft_event_id: {soft_event.id}\n"
            f"slot_id: {slot.id}\n"
            f"slot_start_at: {start_at}\n"
            f"slot_end_at: {end_at}\n\n"
            "Steps:\n"
            '1) Call calendar_manager.get_soft_event with soft_event_id and slot_status="planned".\n'
            "2) Find a slot with id == slot_id and matching start/end.\n"
            f'3) If found, call call_sessions.create_session with goal: "{goal}".\n'
            "4) If not found, do nothing and finish."
        )

    @staticmethod
    def apply_planner_actions(
        actions: Iterable[dict], planner_trace_id: str = ""
    ) -> Tuple[int, int]:
        """
        Apply planner-suggested actions to slots. Expected action shapes:
          - {"type": "create_slot", "soft_event_id": str, "start_at": iso, "end_at": iso, "notify_at": iso?, "rationale": str}
          - {"type": "cancel_slot", "slot_id": str}
          - {"type": "update_slot", "slot_id": str, ...fields}
          - {"type": "promote_slot", "slot_id": str, "summary": str?, "description": str?, "calendar_id"?, "timezone"?}
        Returns (created, updated) counts.
        """
        from orchestration.models import SoftEvent, SoftEventSlot, ScheduledTask
        from orchestration.tools import calendar as cal

        created = updated = 0
        for action in actions:
            atype = (action or {}).get("type")
            if atype == "create_slot":
                try:
                    se = SoftEvent.objects.get(id=action["soft_event_id"])
                except SoftEvent.DoesNotExist:
                    continue
                start_at = SoftEventService._parse_dt(action.get("start_at"))
                end_at = SoftEventService._parse_dt(action.get("end_at"))
                notify_at = SoftEventService._parse_dt(action.get("notify_at"))
                if not start_at or not end_at:
                    continue
                slot = SoftEventSlot.objects.create(
                    soft_event=se,
                    start_at=start_at,
                    end_at=end_at,
                    notify_at=notify_at,
                    rationale=action.get("rationale", ""),
                    planner_trace_id=planner_trace_id,
                    metadata=action.get("metadata") or {},
                )
                created += 1
                SoftEventService.logger.info(
                    "Created soft slot %s for %s", slot.id, se.id
                )
                if se.status == SoftEvent.STATUS_ACTIVE:
                    try:
                        ScheduledTask.objects.create(
                            prompt=SoftEventService._build_soft_event_call_prompt(se, slot),
                            recurrence=ScheduledTask.RECURRENCE_ONCE,
                            start_at=start_at,
                            next_run_at=start_at,
                            status=ScheduledTask.STATUS_ACTIVE,
                            metadata={
                                "type": "soft_event_slot_call",
                                "soft_event_id": str(se.id),
                                "slot_id": str(slot.id),
                                "slot_start_at": start_at.isoformat(),
                                "slot_end_at": end_at.isoformat(),
                            },
                        )
                    except Exception:
                        SoftEventService.logger.exception(
                            "Failed to schedule reminder for soft slot %s", slot.id
                        )
            elif atype == "cancel_slot":
                try:
                    slot = SoftEventSlot.objects.get(id=action["slot_id"])
                except SoftEventSlot.DoesNotExist:
                    continue
                slot.status = SoftEventSlot.STATUS_CANCELED
                slot.save(update_fields=["status", "updated_at"])
                updated += 1
            elif atype == "update_slot":
                try:
                    slot = SoftEventSlot.objects.get(id=action["slot_id"])
                except SoftEventSlot.DoesNotExist:
                    continue
                fields = []
                for key in [
                    "start_at",
                    "end_at",
                    "notify_at",
                    "status",
                    "rationale",
                    "metadata",
                ]:
                    if key in action:
                        val = action[key]
                        if key in {"start_at", "end_at", "notify_at"}:
                            val = SoftEventService._parse_dt(val)
                            if not val:
                                continue
                        setattr(slot, key, val)
                        fields.append(key)
                if planner_trace_id:
                    slot.planner_trace_id = planner_trace_id
                    fields.append("planner_trace_id")
                if fields:
                    slot.save(update_fields=list(set(fields + ["updated_at"])))
                    updated += 1
            elif atype == "promote_slot":
                try:
                    slot = SoftEventSlot.objects.select_related("soft_event").get(
                        id=action["slot_id"]
                    )
                except SoftEventSlot.DoesNotExist:
                    continue
                summary = action.get("summary") or slot.soft_event.title
                description = (
                    action.get("description")
                    or slot.rationale
                    or slot.soft_event.description
                )
                start_at = SoftEventService._parse_dt(
                    action.get("start_at") or slot.start_at
                )
                end_at = SoftEventService._parse_dt(action.get("end_at") or slot.end_at)
                if not start_at or not end_at:
                    continue
                try:
                    resp = cal.create_event(
                        summary=summary,
                        start=start_at.isoformat(),
                        end=end_at.isoformat(),
                        description=description,
                        calendar_id=action.get("calendar_id")
                        or cal.DEFAULT_CALENDAR_ID,
                        timezone=action.get("timezone") or cal.DEFAULT_TIMEZONE,
                    )
                    slot.status = SoftEventSlot.STATUS_PROMOTED
                    slot.metadata["calendar_event_id"] = resp.get("id")
                    slot.save(update_fields=["status", "metadata", "updated_at"])
                    updated += 1
                except Exception as exc:  # pragma: no cover - external API
                    SoftEventService.logger.exception(
                        "Failed to promote slot %s: %s", slot.id, exc
                    )
        return created, updated


class UsageService:
    """
    Helper to log usage events for observability.
    """

    logger = logging.getLogger(__name__)

    @staticmethod
    def log_usage(
        *,
        source: str,
        model: str,
        cache_mode: str = "",
        usage: Optional[dict] = None,
        prompt_cache_key: str = "",
        job: Optional[Job] = None,
    ):
        if not usage:
            return

        # usage may be a dict or OpenAI's ResponseUsage object; normalize via attrs then dict.
        def _val(obj, key, default=None):
            if hasattr(obj, key):
                return getattr(obj, key, default)
            if isinstance(obj, dict):
                return obj.get(key, default)
            return default

        def _first_not_none(*vals, default=0):
            for v in vals:
                if v is not None:
                    return v
            return default

        prompt_tokens = _first_not_none(
            _val(usage, "prompt_tokens", None),
            _val(usage, "input_tokens", None),
        )
        completion_tokens = _first_not_none(
            _val(usage, "completion_tokens", None),
            _val(usage, "output_tokens", None),
        )
        total_tokens = _first_not_none(
            _val(usage, "total_tokens", None),
            (prompt_tokens or 0) + (completion_tokens or 0),
        )
        details = _first_not_none(
            _val(usage, "prompt_tokens_details", None),
            _val(usage, "input_tokens_details", None),
            default={},
        )
        cached_prompt_tokens = _first_not_none(_val(details, "cached_tokens", None))

        if cache_mode and cache_mode != "off":
            try:
                # Use warning level so it shows up with default Django logging.
                UsageService.logger.warning(
                    "Usage detail",
                    extra={
                        "source": source,
                        "cache_mode": cache_mode,
                        "prompt_cache_key": prompt_cache_key,
                        "usage_raw": usage,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                        "cached_prompt_tokens": cached_prompt_tokens,
                    },
                )
            except Exception:
                pass

        pricing = ModelConfigService.get_pricing()
        prompt_cost = completion_cost = total_cost = 0
        if model in pricing:
            p = pricing[model]
            pp = p.get("prompt_per_1k") or 0
            cpp = p.get("cached_prompt_per_1k") or pp
            cp = p.get("completion_per_1k") or 0
            effective_cached = cached_prompt_tokens or 0
            effective_prompt = max((prompt_tokens or 0) - effective_cached, 0)
            prompt_cost = (effective_prompt / 1000) * pp + (
                effective_cached / 1000
            ) * cpp
            completion_cost = (completion_tokens / 1000) * cp
            total_cost = prompt_cost + completion_cost

        UsageEvent.objects.create(
            source=source,
            model=model,
            cache_mode=cache_mode,
            prompt_tokens=prompt_tokens,
            cached_prompt_tokens=cached_prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            prompt_cache_key=prompt_cache_key or "",
            prompt_cost=prompt_cost,
            completion_cost=completion_cost,
            total_cost=total_cost,
            job=job,
            chat=job.chat if job else None,
        )
