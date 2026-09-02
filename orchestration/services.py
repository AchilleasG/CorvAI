from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional, List, Iterable, Tuple
from datetime import datetime, timedelta

from openai import OpenAI
from django.db import transaction, models
from django.conf import settings as django_settings
from django.core.cache import cache
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
    KnowledgeEntity,
)
from orchestration.registry import FunctionRegistry
from orchestration.schemas import (
    FunctionCallPayload,
    FunctionResultPayload,
    MessageEnvelope,
)
from Corv.config import settings

if TYPE_CHECKING:
    from orchestration.models import SoftEvent, SoftEventSlot

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
        call_session=None,
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

        if status == "ok" and isinstance(result, dict):
            origin = {"chat": job.chat} if job and job.chat_id else ({"call_session": call_session} if call_session else {})
            if origin:
                from coding.chat_waits import CodingChatWaitService
                from coding.models import CodingTurn, FeatureDelegation
                if payload.function_id == "coding_sessions.delegate_task":
                    turn = CodingTurn.objects.filter(pk=result.get("delegated_turn_id")).select_related("session").first()
                    if turn: CodingChatWaitService.watch_turn(turn=turn, waiting=bool(result.get("wait_for_completion")), **origin)
                elif payload.function_id == "coding_sessions.delegate_feature":
                    delegation = FeatureDelegation.objects.filter(pk=result.get("id")).select_related("session").first()
                    if delegation: CodingChatWaitService.watch_delegation(delegation=delegation, waiting=bool(result.get("wait_for_completion")), **origin)
                elif payload.function_id == "coding_sessions.answer_decision":
                    turn = CodingTurn.objects.filter(pk=result.get("delegated_turn_id")).select_related("session").first()
                    if turn: CodingChatWaitService.advance_turn(turn=turn, **origin)
                elif payload.function_id == "coding_sessions.resume_feature_delegation":
                    delegation = FeatureDelegation.objects.filter(pk=result.get("id")).first()
                    if delegation: CodingChatWaitService.publish_for_delegation(delegation)
                elif payload.function_id == "coding_sessions.list_conversation_delegations":
                    result = CodingChatWaitService.list_for_origin(include_finished=bool(result.get("include_finished", True)), **origin)
                elif payload.function_id == "coding_sessions.set_conversation_delegation_wait":
                    result = CodingChatWaitService.set_wait(selector=result.get("delegation", ""), waiting=bool(result.get("waiting")), **origin)
            if job:
                file_ids = []
                if result.get("managed_file_id"): file_ids.append(str(result["managed_file_id"]))
                for file_payload in result.get("files", []) if isinstance(result.get("files"), list) else []:
                    if isinstance(file_payload, dict) and file_payload.get("managed_file_id"): file_ids.append(str(file_payload["managed_file_id"]))
                if file_ids:
                    metadata = job.metadata if isinstance(job.metadata, dict) else {}
                    pending = [str(value) for value in metadata.get("pending_file_ids", [])]
                    metadata["pending_file_ids"] = list(dict.fromkeys(pending + file_ids))
                    job.metadata = metadata
                    job.save(update_fields=["metadata", "updated_at"])

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
        expires_at=None,
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
            expires_at=UserInfoService.normalize_note_expiry(expires_at),
        )
        return note

    @staticmethod
    def normalize_note_expiry(value):
        if value in (None, ""):
            return None
        if isinstance(value, str):
            from django.utils.dateparse import parse_datetime
            value = parse_datetime(value.strip())
            if value is None:
                raise ValueError("expires_at must be an ISO 8601 date/time")
        if not isinstance(value, datetime):
            raise ValueError("expires_at must be a date/time")
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value

    @staticmethod
    def active_notes(user_id: Optional[str] = None):
        uid = UserInfoService._normalize_user_id(user_id)
        now = timezone.now()
        return UserNote.objects.filter(user_id=uid, deleted_at__isnull=True).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )

    @staticmethod
    def cleanup_expired_notes(*, now=None) -> int:
        cutoff = now or timezone.now()
        return UserNote.objects.filter(
            deleted_at__isnull=True, expires_at__isnull=False, expires_at__lte=cutoff
        ).update(deleted_at=cutoff, updated_at=cutoff)

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
        expires_at=...,
    ) -> UserNote:
        uid = UserInfoService._normalize_user_id(user_id)
        note = UserInfoService.active_notes(uid).filter(id=note_id).first()
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
        if expires_at is not ...:
            note.expires_at = UserInfoService.normalize_note_expiry(expires_at)
        note.save(
            update_fields=[
                "content_raw",
                "content_canonical",
                "embedding",
                "source",
                "tags",
                "expires_at",
                "updated_at",
            ]
        )
        return note

    @staticmethod
    def delete_note(note_id: str, *, user_id: Optional[str] = None):
        uid = UserInfoService._normalize_user_id(user_id)
        note = UserInfoService.active_notes(uid).filter(id=note_id).first()
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

        qs = UserInfoService.active_notes(uid).filter(embedding__isnull=False)
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
                    "expires_at": n.expires_at,
                    "distance": getattr(n, "distance", None),
                }
            )
        return out


class LocationSearchService:
    """Bounded, cached proxy for user-triggered place lookup."""

    _lock = threading.Lock()
    _last_request_at = 0.0
    CACHE_SECONDS = 60 * 60 * 24 * 7

    @classmethod
    def search(cls, query: str, *, limit: int = 6) -> list[dict]:
        clean = " ".join(str(query or "").split()).strip()
        if len(clean) < 2: raise ValueError("Enter at least two characters to search places")
        limit = max(1, min(int(limit), 10)); key = f"location-search:v1:{clean.casefold()}:{limit}"
        cached = cache.get(key)
        if cached is not None: return cached
        with cls._lock:
            delay = 1.0 - (time.monotonic() - cls._last_request_at)
            if delay > 0: time.sleep(delay)
            import httpx
            base = str(getattr(django_settings, "NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")).rstrip("/")
            response = httpx.get(f"{base}/search", params={"q": clean, "format": "jsonv2", "addressdetails": 1, "limit": limit}, headers={"User-Agent": "CorvAI/1.0 location-note-picker", "Accept-Language": "en"}, timeout=10.0)
            cls._last_request_at = time.monotonic(); response.raise_for_status()
        results=[]
        for row in response.json():
            try: latitude=float(row["lat"]); longitude=float(row["lon"])
            except (KeyError,TypeError,ValueError): continue
            results.append({"display_name":str(row.get("display_name") or ""),"name":str(row.get("name") or row.get("display_name") or ""),"latitude":latitude,"longitude":longitude,"category":str(row.get("category") or ""),"place_type":str(row.get("type") or ""),"importance":float(row.get("importance") or 0)})
        cache.set(key,results,cls.CACHE_SECONDS); return results


class KnowledgeBaseService:
    """Typed knowledge CRUD and unified note/entity semantic retrieval."""

    TYPE_FIELDS = {
        "location": {"required": ("latitude", "longitude"), "array": ()},
        "person": {"required": (), "array": ("facts",)},
    }
    TYPE_HINTS = {
        "location": {"home", "house", "address", "location", "place", "where", "coordinates", "latitude", "longitude", "office", "restaurant", "hotel"},
        "person": {"person", "people", "who", "friend", "family", "mother", "father", "brother", "sister", "partner", "colleague", "relationship"},
    }

    @staticmethod
    def _uid(user_id=None): return UserInfoService._normalize_user_id(user_id)

    @staticmethod
    def _tags(tags):
        clean=[]
        for value in tags or []:
            tag=str(value).strip()[:64]
            if tag and tag not in clean: clean.append(tag)
        return clean[:20]

    @classmethod
    def _validate(cls, entity_type, name, description, data):
        kind=str(entity_type or "").strip().lower()
        if kind not in cls.TYPE_FIELDS: raise ValueError(f"Unsupported knowledge entity type: {kind}")
        clean_name=" ".join(str(name or "").split())
        if not clean_name: raise ValueError("Entity name is required")
        payload=dict(data or {})
        if kind=="location":
            try: latitude=float(payload["latitude"]); longitude=float(payload["longitude"])
            except (KeyError,TypeError,ValueError): raise ValueError("Locations require numeric latitude and longitude")
            if not -90<=latitude<=90 or not -180<=longitude<=180: raise ValueError("Location coordinates are out of range")
            payload.update(latitude=latitude,longitude=longitude)
        if kind=="person":
            relationship=str(payload.get("relationship") or "").strip()
            facts=payload.get("facts") or []
            if not isinstance(facts,list): raise ValueError("Person facts must be an array")
            payload.update(relationship=relationship,facts=[str(f).strip() for f in facts if str(f).strip()])
        return kind,clean_name,str(description or "").strip(),payload

    @staticmethod
    def _document(entity_type,name,description,data,tags):
        parts=[entity_type,name,description]
        if entity_type=="location": parts += [f"latitude {data.get('latitude')}",f"longitude {data.get('longitude')}"]
        elif entity_type=="person": parts += [data.get("relationship","")] + list(data.get("facts") or [])
        parts += list(tags or [])
        return " ".join(str(x) for x in parts if x).strip()

    @staticmethod
    def payload(item, distance=None):
        result={"id":str(item.id),"knowledge_type":item.entity_type,"name":item.name,"description":item.description,"data":item.data or {},"source":item.source,"tags":item.tags or [],"created_at":item.created_at.isoformat() if item.created_at else None,"updated_at":item.updated_at.isoformat() if item.updated_at else None}
        if distance is not None: result["distance"]=float(distance)
        return result

    @classmethod
    def create(cls,entity_type,*,name,description="",data=None,tags=None,user_id=None,source="corv_action"):
        kind,name,description,data=cls._validate(entity_type,name,description,data)
        tags=cls._tags(tags); document=cls._document(kind,name,description,data,tags)
        return KnowledgeEntity.objects.create(user_id=cls._uid(user_id),entity_type=kind,name=name,description=description,data=data,search_text=UserInfoService._canonicalize(document),embedding=UserInfoService._embed_text(document),source=source,tags=tags)

    @classmethod
    def get(cls,entity_id,*,entity_type=None,user_id=None):
        qs=KnowledgeEntity.objects.filter(id=entity_id,user_id=cls._uid(user_id),deleted_at__isnull=True)
        if entity_type: qs=qs.filter(entity_type=entity_type)
        item=qs.first()
        if not item: raise ValueError("Knowledge entity not found")
        return item

    @classmethod
    def update(cls,entity_id,*,entity_type=None,name=None,description=None,data=None,tags=None,user_id=None,source=None):
        item=cls.get(entity_id,entity_type=entity_type,user_id=user_id)
        merged={**(item.data or {}),**(data or {})}
        kind,name,description,merged=cls._validate(item.entity_type,name if name is not None else item.name,description if description is not None else item.description,merged)
        clean_tags=cls._tags(tags if tags is not None else item.tags); document=cls._document(kind,name,description,merged,clean_tags)
        item.name=name; item.description=description; item.data=merged; item.tags=clean_tags; item.search_text=UserInfoService._canonicalize(document); item.embedding=UserInfoService._embed_text(document)
        if source is not None: item.source=source
        item.save(update_fields=["name","description","data","tags","search_text","embedding","source","updated_at"]); return item

    @classmethod
    def delete(cls,entity_id,*,entity_type=None,user_id=None):
        item=cls.get(entity_id,entity_type=entity_type,user_id=user_id); item.deleted_at=timezone.now(); item.save(update_fields=["deleted_at","updated_at"]); return item

    @classmethod
    def preferred_types(cls,query):
        words=set(UserInfoService._canonicalize(query).split()); scored=[]
        for kind,hints in cls.TYPE_HINTS.items():
            score=len(words & hints)
            if score: scored.append((kind,score))
        return [kind for kind,_ in sorted(scored,key=lambda row:-row[1])]

    @classmethod
    def list_type(cls,entity_type,*,query="",tags=None,limit=100,user_id=None):
        if entity_type not in cls.TYPE_FIELDS: raise ValueError("Unsupported knowledge entity type")
        qs=KnowledgeEntity.objects.filter(user_id=cls._uid(user_id),entity_type=entity_type,deleted_at__isnull=True)
        for tag in cls._tags(tags): qs=qs.filter(tags__contains=[tag])
        query=str(query or "").strip()
        if query:
            embedding=UserInfoService._embed_text(UserInfoService._canonicalize(query))
            if embedding:
                from pgvector.django import CosineDistance
                qs=qs.filter(embedding__isnull=False).annotate(distance=CosineDistance("embedding",embedding)).order_by("distance","name")
            else: qs=qs.filter(models.Q(name__icontains=query)|models.Q(description__icontains=query)|models.Q(search_text__icontains=query.lower())).order_by("name")
        else: qs=qs.order_by("name")
        return [cls.payload(item,getattr(item,"distance",None)) for item in qs[:max(1,min(int(limit),500))]]

    @classmethod
    def search(cls,query,*,tags=None,limit=10,user_id=None,entity_types=None):
        query=str(query or "").strip()
        if not query: raise ValueError("Search query is required")
        uid=cls._uid(user_id); clean_tags=cls._tags(tags); embedding=UserInfoService._embed_text(UserInfoService._canonicalize(query)); results=[]
        allowed=set(entity_types or ["note",*cls.TYPE_FIELDS.keys()]); per_limit=max(limit*3,20)
        if "note" in allowed:
            notes=UserInfoService.active_notes(uid)
            for tag in clean_tags: notes=notes.filter(tags__contains=[tag])
            if embedding:
                from pgvector.django import CosineDistance
                notes=notes.filter(embedding__isnull=False).annotate(distance=CosineDistance("embedding",embedding)).order_by("distance")[:per_limit]
            else: notes=notes.filter(models.Q(content_raw__icontains=query)|models.Q(content_canonical__icontains=query.lower()))[:per_limit]
            for note in notes:
                results.append({"id":str(note.id),"knowledge_type":"note","content":note.content_raw,"source":note.source,"tags":note.tags or [],"created_at":note.created_at.isoformat() if note.created_at else None,"updated_at":note.updated_at.isoformat() if note.updated_at else None,"expires_at":note.expires_at.isoformat() if note.expires_at else None,"distance":float(getattr(note,"distance",1.0))})
        entities=KnowledgeEntity.objects.filter(user_id=uid,deleted_at__isnull=True,entity_type__in=[x for x in allowed if x!="note"])
        for tag in clean_tags: entities=entities.filter(tags__contains=[tag])
        if embedding:
            from pgvector.django import CosineDistance
            entities=entities.filter(embedding__isnull=False).annotate(distance=CosineDistance("embedding",embedding)).order_by("distance")[:per_limit]
        else: entities=entities.filter(models.Q(name__icontains=query)|models.Q(description__icontains=query)|models.Q(search_text__icontains=query.lower()))[:per_limit]
        results += [cls.payload(item,getattr(item,"distance",1.0)) for item in entities]
        preferred=cls.preferred_types(query); type_order={kind:index for index,kind in enumerate(preferred)}
        results.sort(key=lambda item:(type_order.get(item["knowledge_type"],len(preferred)),item.get("distance",1.0)))
        return {"query":query,"preferred_types":preferred,"results":results[:max(1,min(int(limit),100))]}


class PersonaService:
    """
    Accessor for Front Man persona instructions.
    """

    VOICE_GUIDE = (
        "Corv voice: sound like a sharp, familiar collaborator, not a customer-support bot. "
        "Default to one or two compact sentences and lead with the useful bit. Be dry-witty and "
        "playful when the moment offers an opening, but never force a joke, repeat a catchphrase, "
        "or turn every reply into banter. Use contractions and natural conversational phrasing. "
        "Be specific to what the user just said; avoid generic filler, canned reassurance, long "
        "preambles, summaries of the obvious, and phrases like 'Certainly', 'Absolutely', 'Great "
        "question', or 'I'd be happy to'. Ask only necessary questions. For errors, decisions, and "
        "safety-critical information, stay crisp and candid; wit must never obscure the facts."
    )
    RETRIEVAL_GUIDE = (
        "Search-before-unknown rule: never say or imply that you do not know, cannot recall, or lack "
        "information before attempting the appropriate available retrieval. For personal facts, preferences, "
        "people, places, history, and other user-specific context, search user_info.search_knowledge first; "
        "the notes system contains extensive personal information. For general, public, uncertain, or current "
        "knowledge, use internet_search.search. If the request could be either personal or general, search personal "
        "knowledge first and then the internet if needed. For personal-knowledge retrieval, prefer broad semantic "
        "search and do not invent tag, source, type, or other deterministic filters; apply one only when the user "
        "explicitly requested that constraint. Fetch a useful set of the most relevant results into context. If a "
        "requested filtered search is empty, retry semantically without filters before concluding nothing exists. "
        "Only state that an answer is unknown after the relevant broad search returned no answer or failed, and "
        "briefly name that concrete outcome."
    )

    NOTE_WRITING_GUIDE = (
        "Note-writing rule: before creating or updating any note, first run a broad semantic "
        "user_info.search_knowledge search for the subject and closely related facts. Review all relevant "
        "results in context so the new note is consistent, avoids duplication, and reuses the user's existing "
        "tag vocabulary; do not add deterministic filters unless the user explicitly requested them. Store "
        "facts in a time-stable form whenever possible. Every temporal reference stored in note content must "
        "be objective and absolute, never relative. Replace words and phrases such as today, tonight, tomorrow, "
        "yesterday, now, currently, this morning, next week, ago, and 'in X days' with the exact calendar date "
        "and, when relevant and known, clock time plus timezone. Express durations as explicit start/end dates. "
        "Attach an exact date to morning/night status when no clock time was supplied; never invent a clock time. "
        "Store a person's birth date or birth year rather than a current age. Never save a value that becomes "
        "false merely because time passes when the invariant fact can be saved instead. If a changing status is "
        "genuinely the fact of interest, include an explicit as-of date/time or use expires_at. Before writing, "
        "scan the proposed note and rewrite every remaining relative temporal expression."
    )

    TEXT_PRESENTATION_GUIDE = (
        "Presentation by channel: in text chat, use polished GitHub-flavored Markdown when it materially "
        "improves scanning. Prefer a short descriptive heading for multi-part answers, compact paragraphs, "
        "bullets for distinct items, bold only for useful labels, and inline Markdown links for sources. "
        "Keep simple answers simple; do not over-format, nest deeply, or add decorative filler. In calls or "
        "other spoken output, never speak Markdown syntax, headings, link notation, or visual-only structure; "
        "use short natural sentences instead."
    )

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
        base = f"{base}\n\n{PersonaService.VOICE_GUIDE}\n\n{PersonaService.RETRIEVAL_GUIDE}\n\n{PersonaService.NOTE_WRITING_GUIDE}\n\n{PersonaService.TEXT_PRESENTATION_GUIDE}"
        profile_block = UserInfoService.format_core_profile_block()
        if profile_block:
            base = f"{base}\n\n{profile_block}"
        from orchestration.presence import PresenceService
        presence_block = PresenceService.prompt_block()
        if presence_block:
            base = f"{base}\n\n{presence_block}"
        return base


class ModelConfigService:
    """
    Accessor for dynamic model selection stored in OrchestrationSetting.
    """

    DEFAULT_FRONTMAN_MODEL = "gpt-5-mini"
    DEFAULT_CALLER_MODEL = "gpt-5-mini"
    DEFAULT_SOFT_PLANNER_MODEL = ""
    DEFAULT_STUDY_MODEL = "gpt-5-mini"
    DEFAULT_CACHE_MODE = "off"
    DEFAULT_PRICING_JSON = "{}"
    DEFAULT_USER_INFO_EMBED_MODEL = "text-embedding-3-small"
    DEFAULT_MAX_FUNCTION_RESULT_CHARS = 6000
    # gpt-5.4-mini supports a 400k context window. Keep ample headroom for
    # persona/tool definitions, reasoning, and the response itself.
    DEFAULT_CHAT_CONTEXT_TOKENS = 160000
    DEFAULT_CHAT_SUMMARY_TOKENS = 6000
    DEFAULT_CALL_VOICE = "marin"
    CALL_VOICES = ("marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")

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
    def get_soft_planner_model() -> str:
        return ModelConfigService.get_setting(
            "soft_planner_model", ModelConfigService.get_caller_model()
        )

    @staticmethod
    def get_study_model() -> str:
        return ModelConfigService.get_setting(
            "study_model", ModelConfigService.DEFAULT_STUDY_MODEL
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
        Returns a dict of model pricing from setting 'model_pricing'.
        Supported keys per model include:
        - prompt_per_1k / cached_prompt_per_1k / completion_per_1k
        - prompt_per_1m / cached_prompt_per_1m / completion_per_1m
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

    @staticmethod
    def get_call_voice() -> str:
        voice = ModelConfigService.get_setting(
            "call_voice", ModelConfigService.DEFAULT_CALL_VOICE
        ).lower()
        return voice if voice in ModelConfigService.CALL_VOICES else ModelConfigService.DEFAULT_CALL_VOICE

    @staticmethod
    def get_call_voice_options() -> list[str]:
        return list(ModelConfigService.CALL_VOICES)

    @staticmethod
    def get_chat_context_tokens() -> int:
        """Token budget for persisted chat history (excluding prompts and tools)."""
        try:
            raw = ModelConfigService.get_setting(
                "chat_context_tokens",
                str(ModelConfigService.DEFAULT_CHAT_CONTEXT_TOKENS),
            )
            return min(max(int(raw), 8000), 300000)
        except (TypeError, ValueError):
            return ModelConfigService.DEFAULT_CHAT_CONTEXT_TOKENS

    @staticmethod
    def get_chat_summary_tokens() -> int:
        """Maximum size requested for the rolling long-term memory summary."""
        try:
            raw = ModelConfigService.get_setting(
                "chat_summary_tokens",
                str(ModelConfigService.DEFAULT_CHAT_SUMMARY_TOKENS),
            )
            return min(max(int(raw), 1000), 16000)
        except (TypeError, ValueError):
            return ModelConfigService.DEFAULT_CHAT_SUMMARY_TOKENS


def _rate_per_token(pricing_row: dict, base_key: str) -> float:
    per_1m = pricing_row.get(f"{base_key}_per_1m")
    if per_1m is not None:
        return float(per_1m) / 1_000_000
    per_1k = pricing_row.get(f"{base_key}_per_1k")
    if per_1k is not None:
        return float(per_1k) / 1_000
    return 0.0


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
                min_minutes = max(int(se.min_duration_minutes or 1), 1)
                preferred_minutes = max(int(se.preferred_duration_minutes or min_minutes), min_minutes)
                requested_minutes = int((end_at - start_at).total_seconds() // 60)
                if requested_minutes < min_minutes:
                    continue
                if requested_minutes > preferred_minutes:
                    end_at = start_at + timedelta(minutes=preferred_minutes)
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
                    slot = SoftEventSlot.objects.select_related("soft_event").get(id=action["slot_id"])
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
                if "start_at" in fields or "end_at" in fields:
                    min_minutes = max(int(slot.soft_event.min_duration_minutes or 1), 1)
                    preferred_minutes = max(
                        int(slot.soft_event.preferred_duration_minutes or min_minutes),
                        min_minutes,
                    )
                    duration_minutes = int((slot.end_at - slot.start_at).total_seconds() // 60)
                    if duration_minutes < min_minutes:
                        continue
                    if duration_minutes > preferred_minutes:
                        slot.end_at = slot.start_at + timedelta(minutes=preferred_minutes)
                        fields.append("end_at")
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
            pp = _rate_per_token(p, "prompt")
            cpp = _rate_per_token(p, "cached_prompt") or pp
            cp = _rate_per_token(p, "completion")
            effective_cached = cached_prompt_tokens or 0
            effective_prompt = max((prompt_tokens or 0) - effective_cached, 0)
            prompt_cost = (effective_prompt * pp) + (effective_cached * cpp)
            completion_cost = completion_tokens * cp
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
