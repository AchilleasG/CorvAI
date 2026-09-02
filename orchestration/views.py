from typing import List, Optional
import logging
import json
import base64
from uuid import UUID
from ninja import Router
from ninja.errors import HttpError

from django.db import OperationalError, transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from datetime import timedelta
from django.utils import timezone
from datetime import datetime

from orchestration.api_schemas import (
    HardEventTaskLinkOut,
    JobOut,
    ObjectiveLogOut,
    ObjectiveOut,
    ObjectiveTaskOut,
    ObjectiveTaskPickerOut,
    ScheduledTaskOut,
    UpdateScheduledTaskIn,
    ScheduledTaskRunOut,
    ScheduledTaskLogOut,
    PushTokenOut,
    UserMessageOut,
    CallSessionOut,
    CallTranscriptEntryOut,
)
from orchestration.models import (
    Job,
    JobEvent,
    Objective,
    ObjectiveLog,
    ObjectiveTask,
    HardEventTaskLink,
    UsageEvent,
    SoftEvent,
    SoftEventSlot,
    SoftEventTask,
    ToolModule,
    ScheduledTask,
    ScheduledTaskRun,
    ScheduledTaskLogEntry,
    PushToken,
    UserMessage,
    CallSession,
    CallTranscriptEntry,
    UserNote,
    KnowledgeEntity,
)
from orchestration.objectives import ObjectiveService
from orchestration.call_processing import (
    create_call_session,
    notify_incoming_call,
    accept_call,
    complete_call,
    execute_call_action,
    mark_call_missed,
    should_end_call,
    AUTOMATIC_CALL_COMPLETION_ENABLED,
)
from orchestration.notifications import send_push_to_all
from Corv.config import settings as corv_settings
import httpx
from orchestration.services import JobService, KnowledgeBaseService, LocationSearchService, ModelConfigService, PersonaService, UserInfoService
from chat.models import ChatMessage
from chat.schemas import MessageOut
from orchestration.tools.calendar import list_events
from orchestration.tools import calendar_manager, soft_events
from orchestration.tasks import run_calendar_replan_job
from coding.auth import CodexAuthService
from orchestration.presence import PresenceService

router = Router(tags=["orchestration"])
logger = logging.getLogger(__name__)


@router.post("/presence")
def update_presence(request):
    try:
        return PresenceService.update(_request_json_dict(request))
    except ValueError as exc:
        raise HttpError(400, str(exc))


def _request_json_dict(request) -> dict:
    try:
        raw = request.body.decode("utf-8") if getattr(request, "body", None) else ""
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@router.get("/jobs", response=List[JobOut])
def list_jobs(request, chat_id: Optional[UUID] = None, status: Optional[str] = None):
    qs = Job.objects.all().order_by("-created_at")
    if chat_id:
        qs = qs.filter(chat_id=chat_id)
    if status:
        qs = qs.filter(status=status)
    return [JobOut.from_model(job) for job in qs[:50]]


@router.get("/jobs/{job_id}", response=JobOut)
def get_job(request, job_id: UUID):
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        raise HttpError(404, "Job not found")
    return JobOut.from_model(job)


@router.post("/jobs/{job_id}/cancel", response=JobOut)
def cancel_job(request, job_id: UUID):
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        raise HttpError(404, "Job not found")
    JobService.request_cancel(job, reason="User requested cancel from UI")
    return JobOut.from_model(job)


@router.get("/jobs/{job_id}/messages", response=List[MessageOut])
def job_messages(request, job_id: UUID):
    messages = ChatMessage.objects.filter(job_id=job_id).order_by("created_at")
    return [
        {
            "id": m.id,
            "role": m.role,
            "text": m.text,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "message_type": m.message_type,
            "audience": m.audience,
            "trace_id": m.trace_id or None,
            "call_id": m.call_id or None,
            "job_id": m.job_id if getattr(m, "job_id", None) else None,
        }
        for m in messages
    ]


@router.get("/jobs/{job_id}/events")
def job_events(request, job_id: UUID):
    try:
        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            raise HttpError(404, "Job not found")

        events = JobEvent.objects.filter(job=job).order_by("created_at")
        return {
            "job_id": str(job.id),
            "events": [
                {
                    "id": str(event.id),
                    "role": event.role,
                    "event_type": event.event_type,
                    "visibility": event.visibility,
                    "message": event.message,
                    "payload": event.payload,
                    "call_id": event.call_id or None,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }
                for event in events
            ],
        }
    except OperationalError:
        logger.warning("job_events unavailable: database is not ready", exc_info=True)
        return {"job_id": str(job_id), "events": []}


@router.get("/usage/recent")
def usage_recent(request, limit: int = 50):
    events = UsageEvent.objects.all().order_by("-created_at")[:limit]
    return [
        {
            "id": str(e.id),
            "created_at": e.created_at.isoformat(),
            "source": e.source,
            "model": e.model,
            "cache_mode": e.cache_mode,
            "prompt_tokens": e.prompt_tokens,
            "cached_prompt_tokens": e.cached_prompt_tokens,
            "completion_tokens": e.completion_tokens,
            "total_tokens": e.total_tokens,
            "prompt_cost": float(e.prompt_cost),
            "completion_cost": float(e.completion_cost),
            "total_cost": float(e.total_cost),
        }
        for e in events
    ]


@router.get("/usage/summary")
def usage_summary(request, days: int = 7):
    cutoff = timezone.now() - timedelta(days=days)
    qs = (
        UsageEvent.objects.filter(created_at__gte=cutoff)
        .annotate()
        .values("source")
        .annotate(
            prompt_tokens=Sum("prompt_tokens"),
            cached_prompt_tokens=Sum("cached_prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
            total_tokens=Sum("total_tokens"),
            prompt_cost=Sum("prompt_cost"),
            completion_cost=Sum("completion_cost"),
            total_cost=Sum("total_cost"),
        )
    )
    by_source = {row["source"]: row for row in qs}
    totals = UsageEvent.objects.filter(created_at__gte=cutoff).aggregate(
        prompt_tokens=Sum("prompt_tokens"),
        cached_prompt_tokens=Sum("cached_prompt_tokens"),
        completion_tokens=Sum("completion_tokens"),
        total_tokens=Sum("total_tokens"),
        prompt_cost=Sum("prompt_cost"),
        completion_cost=Sum("completion_cost"),
        total_cost=Sum("total_cost"),
    )
    return {
        "since": cutoff.isoformat(),
        "by_source": by_source,
        "totals": totals,
    }


@router.get("/settings")
def get_settings(request):
    return {
        "frontman_model": ModelConfigService.get_frontman_model(),
        "caller_model": ModelConfigService.get_caller_model(),
        "soft_planner_model": ModelConfigService.get_soft_planner_model(),
        "study_model": ModelConfigService.get_study_model(),
        "cache_mode": ModelConfigService.get_cache_mode(),
        "max_function_result_chars": ModelConfigService.get_max_function_result_chars(),
        "call_voice": ModelConfigService.get_call_voice(),
        "call_voice_options": ModelConfigService.get_call_voice_options(),
        **CodexAuthService.settings_payload(),
    }


def _note_payload(note: UserNote) -> dict:
    return {
        "id": str(note.id),
        "content": note.content_raw,
        "source": note.source,
        "tags": note.tags or [],
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        "expires_at": note.expires_at.isoformat() if note.expires_at else None,
        "is_timed": note.expires_at is not None,
    }


def _clean_note_tags(value) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = str(item).strip()
        if tag and tag not in tags:
            tags.append(tag[:64])
    return tags[:20]


@router.get("/notes")
def list_notes(request, query: str = "", tags: str = "", limit: int = 200):
    qs = UserInfoService.active_notes()
    clean_query = query.strip()
    if clean_query:
        qs = qs.filter(
            Q(content_raw__icontains=clean_query)
            | Q(content_canonical__icontains=clean_query.lower())
            | Q(source__icontains=clean_query)
        )
    selected_tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    for tag in selected_tags:
        qs = qs.filter(tags__contains=[tag])
    notes = list(qs.order_by("-updated_at")[: min(max(limit, 1), 500)])
    all_tags = sorted(
        {
            tag
            for values in [
                *UserInfoService.active_notes().values_list("tags", flat=True),
                *KnowledgeEntity.objects.filter(user_id=UserInfoService.DEFAULT_USER_ID, deleted_at__isnull=True).values_list("tags", flat=True),
            ]
            for tag in (values or []) if tag
        },
        key=str.casefold,
    )
    return {"notes": [_note_payload(note) for note in notes], "tags": all_tags, "count": len(notes)}


@router.post("/notes")
def create_note(request):
    payload = _request_json_dict(request)
    content = str(payload.get("content") or "").strip()
    if not content:
        raise HttpError(400, "Note text is required")
    try:
        note = UserInfoService.add_note(
            content=content,
            source="notes_ui",
            tags=_clean_note_tags(payload.get("tags")),
            expires_at=payload.get("expires_at"),
        )
    except Exception as exc:
        logger.exception("Failed to create note")
        raise HttpError(502, f"Could not create note: {exc}")
    return _note_payload(note)


@router.patch("/notes/{note_id}")
def update_note(request, note_id: UUID):
    existing = UserNote.objects.filter(
        id=note_id,
        user_id=UserInfoService.DEFAULT_USER_ID,
        deleted_at__isnull=True,
    ).first()
    if existing is None:
        raise HttpError(404, "Note not found")
    payload = _request_json_dict(request)
    content = str(payload.get("content", existing.content_raw) or "").strip()
    if not content:
        raise HttpError(400, "Note text is required")
    try:
        note = UserInfoService.update_note(
            str(note_id),
            content=content,
            source=existing.source,
            tags=_clean_note_tags(payload.get("tags", existing.tags)),
            expires_at=payload.get("expires_at", ...),
        )
    except ValueError:
        raise HttpError(404, "Note not found")
    except Exception as exc:
        logger.exception("Failed to update note id=%s", note_id)
        raise HttpError(502, f"Could not update note: {exc}")
    return _note_payload(note)


@router.delete("/notes/{note_id}")
def delete_note(request, note_id: UUID):
    note = UserNote.objects.filter(
        id=note_id,
        user_id=UserInfoService.DEFAULT_USER_ID,
        deleted_at__isnull=True,
    ).first()
    if note is None:
        raise HttpError(404, "Note not found")
    UserInfoService.delete_note(str(note_id))
    return {"deleted": True, "id": str(note_id)}


def _knowledge_payload_data(entity_type: str, payload: dict, existing=None) -> tuple[str, str, dict, list]:
    name=str(payload.get("name",existing.name if existing else "") or "").strip()
    description=str(payload.get("description",existing.description if existing else "") or "").strip()
    data=dict(existing.data or {}) if existing else {}
    if isinstance(payload.get("data"),dict): data.update(payload["data"])
    if entity_type=="location":
        for field in ("latitude","longitude"):
            if field in payload: data[field]=payload[field]
    elif entity_type=="person":
        for field in ("relationship","facts"):
            if field in payload: data[field]=payload[field]
    tags=_clean_note_tags(payload.get("tags",existing.tags if existing else []))
    return name,description,data,tags


@router.get("/knowledge/location-search")
def search_locations_for_note(request, query: str, limit: int=6):
    try: return {"query":query,"results":LocationSearchService.search(query,limit=limit),"attribution":"Search data © OpenStreetMap contributors"}
    except ValueError as exc: raise HttpError(400,str(exc))
    except Exception as exc: logger.exception("Location search failed"); raise HttpError(502,f"Location search is temporarily unavailable: {exc}")


@router.get("/knowledge/search")
def search_knowledge(request, query: str, tags: str="", limit: int=20):
    try: return KnowledgeBaseService.search(query,tags=[x.strip() for x in tags.split(",") if x.strip()],limit=limit)
    except ValueError as exc: raise HttpError(400,str(exc))


@router.get("/knowledge/tags")
def list_knowledge_tags(request):
    note_tags=UserInfoService.active_notes().values_list("tags",flat=True)
    entity_tags=KnowledgeEntity.objects.filter(user_id=UserInfoService.DEFAULT_USER_ID,deleted_at__isnull=True).values_list("tags",flat=True)
    return {"tags":sorted({tag for values in [*note_tags,*entity_tags] for tag in (values or []) if tag},key=str.casefold)}


@router.get("/knowledge/{entity_type}")
def list_knowledge_type(request, entity_type: str, query: str="", tags: str="", limit: int=200):
    try: return {"entity_type":entity_type,"entities":KnowledgeBaseService.list_type(entity_type,query=query,tags=[x.strip() for x in tags.split(",") if x.strip()],limit=limit)}
    except ValueError as exc: raise HttpError(400,str(exc))


@router.post("/knowledge/{entity_type}")
def create_knowledge_entity(request, entity_type: str):
    payload=_request_json_dict(request); name,description,data,tags=_knowledge_payload_data(entity_type,payload)
    try: return KnowledgeBaseService.payload(KnowledgeBaseService.create(entity_type,name=name,description=description,data=data,tags=tags,source="notes_ui"))
    except ValueError as exc: raise HttpError(400,str(exc))
    except Exception as exc: logger.exception("Failed to create knowledge entity"); raise HttpError(502,f"Could not create entity: {exc}")


@router.get("/knowledge/{entity_type}/{entity_id}")
def get_knowledge_entity(request, entity_type: str, entity_id: UUID):
    try: return KnowledgeBaseService.payload(KnowledgeBaseService.get(entity_id,entity_type=entity_type))
    except ValueError as exc: raise HttpError(404,str(exc))


@router.patch("/knowledge/{entity_type}/{entity_id}")
def update_knowledge_entity(request, entity_type: str, entity_id: UUID):
    try:
        existing=KnowledgeBaseService.get(entity_id,entity_type=entity_type); payload=_request_json_dict(request); name,description,data,tags=_knowledge_payload_data(entity_type,payload,existing)
        return KnowledgeBaseService.payload(KnowledgeBaseService.update(entity_id,entity_type=entity_type,name=name,description=description,data=data,tags=tags,source=existing.source))
    except ValueError as exc: raise HttpError(404 if "not found" in str(exc).lower() else 400,str(exc))
    except Exception as exc: logger.exception("Failed to update knowledge entity"); raise HttpError(502,f"Could not update entity: {exc}")


@router.delete("/knowledge/{entity_type}/{entity_id}")
def delete_knowledge_entity(request, entity_type: str, entity_id: UUID):
    try: KnowledgeBaseService.delete(entity_id,entity_type=entity_type); return {"deleted":True,"id":str(entity_id)}
    except ValueError as exc: raise HttpError(404,str(exc))


@router.post("/push_tokens", response=PushTokenOut)
def register_push_token(request, token: str, platform: str = "unknown"):
    obj, _ = PushToken.objects.update_or_create(
        token=token,
        defaults={"platform": platform},
    )
    return PushTokenOut(
        id=obj.id,
        token=obj.token,
        platform=obj.platform,
        created_at=obj.created_at.isoformat() if obj.created_at else None,
        last_seen_at=obj.last_seen_at.isoformat() if obj.last_seen_at else None,
    )


@router.get("/messages", response=List[UserMessageOut])
def list_messages(request, unread_only: bool = False):
    qs = UserMessage.objects.all()
    if unread_only:
        qs = qs.filter(read_at__isnull=True)
    qs = qs.order_by("-created_at")[:100]
    return [
        UserMessageOut(
            id=m.id,
            title=m.title,
            body=m.body,
            kind=m.kind,
            read_at=m.read_at.isoformat() if m.read_at else None,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in qs
    ]


@router.patch("/messages/{message_id}/read", response=UserMessageOut)
def mark_message_read(request, message_id: UUID):
    try:
        msg = UserMessage.objects.get(id=message_id)
    except UserMessage.DoesNotExist:
        raise HttpError(404, "Message not found")
    if not msg.read_at:
        msg.read_at = timezone.now()
        msg.save(update_fields=["read_at"])
    return UserMessageOut(
        id=msg.id,
        title=msg.title,
        body=msg.body,
        kind=msg.kind,
        read_at=msg.read_at.isoformat() if msg.read_at else None,
        created_at=msg.created_at.isoformat() if msg.created_at else None,
    )


@router.get("/call_sessions", response=List[CallSessionOut])
def list_call_sessions(
    request, status: Optional[str] = None, platform: Optional[str] = None
):
    qs = CallSession.objects.all()
    if platform == "mobile":
        # Keep legacy/system sessions visible while excluding only explicit web calls.
        qs = qs.filter(Q(metadata__origin__isnull=True) | ~Q(metadata__origin="web"))
    if status:
        qs = qs.filter(status=status)
    qs = qs.order_by("-created_at")[:100]
    return [
        CallSessionOut(
            id=s.id,
            goal=s.goal,
            status=s.status,
            scheduled_for=s.scheduled_for.isoformat() if s.scheduled_for else None,
            ringing_started_at=s.ringing_started_at.isoformat() if s.ringing_started_at else None,
            started_at=s.started_at.isoformat() if s.started_at else None,
            ended_at=s.ended_at.isoformat() if s.ended_at else None,
            summary=s.summary or "",
            created_at=s.created_at.isoformat() if s.created_at else None,
            updated_at=s.updated_at.isoformat() if s.updated_at else None,
        )
        for s in qs
    ]


def _call_origin_from_request(request, requested_origin: str) -> str:
    """Classify browser calls server-side instead of trusting one client query flag."""
    if requested_origin in {"web", "mobile"}:
        return requested_origin
    headers = getattr(request, "headers", {}) or {}
    # Native mobile requests do not send browser Origin/Referer headers. Browser
    # requests do, including when Vite proxies the API to Django.
    if headers.get("Origin") or headers.get("Referer"):
        return "web"
    return "corv"


@router.post("/call_sessions", response=CallSessionOut)
def create_call(
    request,
    goal: str,
    scheduled_for: Optional[str] = None,
    origin: str = "corv",
):
    dt = _parse_dt(scheduled_for) if scheduled_for else None
    normalized_origin = _call_origin_from_request(request, origin)
    session = create_call_session(goal=goal, scheduled_for=dt, origin=normalized_origin)
    return CallSessionOut(
        id=session.id,
        goal=session.goal,
        status=session.status,
        scheduled_for=session.scheduled_for.isoformat() if session.scheduled_for else None,
        ringing_started_at=session.ringing_started_at.isoformat() if session.ringing_started_at else None,
        started_at=session.started_at.isoformat() if session.started_at else None,
        ended_at=session.ended_at.isoformat() if session.ended_at else None,
        summary=session.summary or "",
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
    )


@router.patch("/call_sessions/{session_id}", response=CallSessionOut)
def update_call_session(
    request,
    session_id: UUID,
    status: Optional[str] = None,
):
    try:
        session = CallSession.objects.get(id=session_id)
    except CallSession.DoesNotExist:
        raise HttpError(404, "Call session not found")

    if status:
        if status == CallSession.STATUS_IN_CALL:
            accept_call(session)
        elif status == CallSession.STATUS_COMPLETED:
            complete_call(session)
        elif status == CallSession.STATUS_MISSED:
            mark_call_missed(session)
        else:
            session.status = status
            session.save(update_fields=["status", "updated_at"])

    return CallSessionOut(
        id=session.id,
        goal=session.goal,
        status=session.status,
        scheduled_for=session.scheduled_for.isoformat() if session.scheduled_for else None,
        ringing_started_at=session.ringing_started_at.isoformat() if session.ringing_started_at else None,
        started_at=session.started_at.isoformat() if session.started_at else None,
        ended_at=session.ended_at.isoformat() if session.ended_at else None,
        summary=session.summary or "",
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
    )


@router.post("/call_sessions/{session_id}/transcript", response=CallTranscriptEntryOut)
def add_transcript_entry(
    request,
    session_id: UUID,
    role: str,
    content: str,
):
    try:
        session = CallSession.objects.get(id=session_id)
    except CallSession.DoesNotExist:
        raise HttpError(404, "Call session not found")
    entry = CallTranscriptEntry.objects.create(session=session, role=role, content=content)
    logger.info("call_transcript session=%s role=%s content=%s", session.id, role, content)
    end_call = False
    if (
        AUTOMATIC_CALL_COMPLETION_ENABLED
        and session.status == CallSession.STATUS_IN_CALL
        and role == "assistant"
    ):
        try:
            end_call = should_end_call(session)
        except Exception:
            end_call = False
        if end_call:
            complete_call(session)
    logger.info("call_monitor_result session=%s end_call=%s", session.id, end_call)
    return CallTranscriptEntryOut(
        id=entry.id,
        role=entry.role,
        content=entry.content,
        created_at=entry.created_at.isoformat() if entry.created_at else None,
        end_call=end_call,
    )


@router.post("/call_sessions/{session_id}/notify")
def notify_call_session(request, session_id: UUID):
    try:
        session = CallSession.objects.get(id=session_id)
    except CallSession.DoesNotExist:
        raise HttpError(404, "Call session not found")
    notify_incoming_call(session)
    return {"ok": True}


@router.post("/call_sessions/{session_id}/realtime_token")
def create_realtime_token(
    request,
    session_id: UUID,
    model: Optional[str] = None,
    manual_turn_detection: bool = False,
):
    try:
        session = CallSession.objects.get(id=session_id)
    except CallSession.DoesNotExist:
        raise HttpError(404, "Call session not found")

    api_key = corv_settings.openai_key
    if not api_key:
        raise HttpError(500, "OpenAI key not configured")

    model_name = model or "gpt-realtime-2.1"
    payload = {
        "session": {
            "type": "realtime",
            "model": model_name,
            "instructions": (
                f"{PersonaService.build_persona_prompt()}\n\n"
                f"Call goal: {session.goal}. You are Corv, with the same capabilities as text mode. "
                "This is spoken conversation: usually answer in one short sentence, occasionally two. "
                "Sound quick, warm, and dry-witty rather than polished or generic. Never narrate obvious "
                "steps, deliver mini-essays, or force a joke. Use plain words only, with no markdown, "
                "bullets, emoji, symbols, or special formatting. When the user asks you to perform an "
                "action, always call perform_corv_action, wait for its result, then report it briefly. You "
                "have Corv's full action capabilities through that tool: before saying you do not know, "
                "cannot do something, or lack access, actively try the relevant available actions and useful "
                "fallbacks. Only admit a limitation after those routes are genuinely exhausted, and state the "
                "specific blocker without a speech. New Codex delegations wait by default without asking "
                "first. The user may interrupt, resume, or switch waits and may track multiple concurrent "
                "delegations by name."
            ),
            "audio": {
                "input": {"transcription": {"model": "gpt-4o-mini-transcribe"}, **({"turn_detection": None} if manual_turn_detection else {})},
                "output": {"voice": ModelConfigService.get_call_voice()},
            },
            "tools": [{
                "type": "function", "name": "perform_corv_action",
                "description": "Perform an action with Corv's full text-mode tools and return the outcome.",
                "parameters": {
                    "type": "object",
                    "properties": {"instruction": {"type": "string"}},
                    "required": ["instruction"],
                },
            }],
        },
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        raise HttpError(502, f"Failed to create realtime session: {exc}")


@router.post("/call_sessions/{session_id}/action")
def run_realtime_call_action(request, session_id: UUID, instruction: str):
    try:
        session = CallSession.objects.get(id=session_id)
    except CallSession.DoesNotExist:
        raise HttpError(404, "Call session not found")
    if session.status != CallSession.STATUS_IN_CALL:
        raise HttpError(409, "Call is not active")
    try:
        return {"result": execute_call_action(session, instruction)}
    except Exception as exc:
        logger.exception("Realtime call action failed session=%s", session.id)
        raise HttpError(500, f"Action failed: {exc}")


@router.get("/call_sessions/{session_id}/delegations")
def call_delegation_state(request, session_id: UUID, after: str = ""):
    session = get_object_or_404(CallSession, id=session_id)
    from coding.chat_waits import CodingChatWaitService
    from django.utils.dateparse import parse_datetime
    queryset = session.transcript_entries.filter(role="system", content__startswith="[Delegation update:")
    parsed = parse_datetime(after) if after else None
    if parsed:
        queryset = queryset.filter(created_at__gt=parsed)
    updates = [{"id": str(x.pk), "content": x.content.split("] ", 1)[-1], "created_at": x.created_at.isoformat()} for x in queryset.order_by("created_at")]
    state = CodingChatWaitService.list_for_origin(call_session=session)
    state.update({"updates": updates, "cursor": timezone.now().isoformat()})
    return state

@router.get("/scheduled_tasks", response=List[ScheduledTaskOut])
def list_scheduled_tasks(request):
    tasks = ScheduledTask.objects.all().order_by("status", "next_run_at", "-created_at")
    return [ScheduledTaskOut.from_model(t) for t in tasks]


@router.post("/scheduled_tasks", response=ScheduledTaskOut)
def create_scheduled_task(
    request,
    prompt: str,
    start_at: Optional[str] = None,
    recurrence: str = ScheduledTask.RECURRENCE_ONCE,
):
    if recurrence not in dict(ScheduledTask.RECURRENCE_CHOICES):
        raise HttpError(400, "Invalid recurrence value")
    start_dt = _parse_dt(start_at) or timezone.now()
    task = ScheduledTask.objects.create(
        prompt=prompt,
        recurrence=recurrence,
        start_at=start_dt,
        next_run_at=start_dt,
        status=ScheduledTask.STATUS_ACTIVE,
    )
    return ScheduledTaskOut.from_model(task)


@router.patch("/scheduled_tasks/{task_id}", response=ScheduledTaskOut)
def update_scheduled_task(
    request,
    task_id: UUID,
    payload: UpdateScheduledTaskIn,
):
    try:
        task = ScheduledTask.objects.get(id=task_id)
    except ScheduledTask.DoesNotExist:
        raise HttpError(404, "Scheduled task not found")

    if payload.recurrence and payload.recurrence not in dict(ScheduledTask.RECURRENCE_CHOICES):
        raise HttpError(400, "Invalid recurrence value")
    if payload.status and payload.status not in dict(ScheduledTask.STATUS_CHOICES):
        raise HttpError(400, "Invalid status value")

    if payload.prompt is not None:
        task.prompt = payload.prompt
    if payload.recurrence is not None:
        task.recurrence = payload.recurrence
    if payload.start_at is not None:
        dt = _parse_dt(payload.start_at)
        if not dt:
            raise HttpError(400, "Invalid start_at datetime")
        task.start_at = dt
        task.next_run_at = dt if task.status == ScheduledTask.STATUS_ACTIVE else task.next_run_at
    if payload.status is not None:
        task.status = payload.status
        if payload.status == ScheduledTask.STATUS_ACTIVE and task.next_run_at is None:
            task.next_run_at = task.start_at
        if payload.status != ScheduledTask.STATUS_ACTIVE:
            task.is_running = False

    task.save(update_fields=["prompt", "recurrence", "start_at", "next_run_at", "status", "is_running", "updated_at"])
    return ScheduledTaskOut.from_model(task)


@router.get("/scheduled_tasks/{task_id}/runs", response=List[ScheduledTaskRunOut])
def list_scheduled_task_runs(request, task_id: UUID):
    try:
        task = ScheduledTask.objects.get(id=task_id)
    except ScheduledTask.DoesNotExist:
        raise HttpError(404, "Scheduled task not found")
    runs = ScheduledTaskRun.objects.filter(task=task).order_by("-started_at")[:50]
    out = []
    for run in runs:
        logs = ScheduledTaskLogEntry.objects.filter(run=run).order_by("created_at")
        out.append(
            ScheduledTaskRunOut(
                id=run.id,
                status=run.status,
                started_at=run.started_at.isoformat() if run.started_at else None,
                finished_at=run.finished_at.isoformat() if run.finished_at else None,
                summary=run.summary or "",
                error_summary=run.error_summary or "",
                log_entries=[
                    ScheduledTaskLogOut(
                        id=entry.id,
                        role=entry.role,
                        level=entry.level,
                        message=entry.message,
                        created_at=entry.created_at.isoformat() if entry.created_at else None,
                    )
                    for entry in logs
                ],
            )
        )
    return out


@router.post("/settings")
def set_settings(
    request,
    frontman_model: Optional[str] = None,
    caller_model: Optional[str] = None,
    soft_planner_model: Optional[str] = None,
    study_model: Optional[str] = None,
    cache_mode: Optional[str] = None,
    max_function_result_chars: Optional[int] = None,
    call_voice: Optional[str] = None,
    codex_auth_mode: Optional[str] = None,
    codex_api_key: Optional[str] = None,
):
    body_payload = {}
    try:
        if getattr(request, "body", None):
            parsed = json.loads(request.body.decode("utf-8"))
            if isinstance(parsed, dict):
                body_payload = parsed
    except Exception:
        body_payload = {}

    frontman_model = body_payload.get("frontman_model", frontman_model)
    caller_model = body_payload.get("caller_model", caller_model)
    soft_planner_model = body_payload.get("soft_planner_model", soft_planner_model)
    study_model = body_payload.get("study_model", study_model)
    cache_mode = body_payload.get("cache_mode", cache_mode)
    max_function_result_chars = body_payload.get("max_function_result_chars", max_function_result_chars)
    call_voice = body_payload.get("call_voice", call_voice)
    codex_auth_mode = body_payload.get("codex_auth_mode", codex_auth_mode)
    codex_api_key = body_payload.get("codex_api_key", codex_api_key)

    if frontman_model:
        ModelConfigService.set_setting("frontman_model", frontman_model)
    if caller_model:
        ModelConfigService.set_setting("caller_model", caller_model)
    if soft_planner_model:
        ModelConfigService.set_setting("soft_planner_model", soft_planner_model)
    if study_model:
        ModelConfigService.set_setting("study_model", study_model)
    if cache_mode:
        ModelConfigService.set_setting("cache_mode", cache_mode.lower())
    if max_function_result_chars is not None:
        ModelConfigService.set_setting("max_function_result_chars", str(max_function_result_chars))
    if call_voice is not None:
        normalized_voice = str(call_voice).lower()
        if normalized_voice not in ModelConfigService.CALL_VOICES:
            raise HttpError(400, "Unsupported Corv voice")
        ModelConfigService.set_setting("call_voice", normalized_voice)
    if codex_auth_mode is not None or codex_api_key:
        try:
            CodexAuthService.update(codex_auth_mode, codex_api_key)
        except (RuntimeError, ValueError) as exc:
            raise HttpError(400, str(exc))
    return {
        "frontman_model": ModelConfigService.get_frontman_model(),
        "caller_model": ModelConfigService.get_caller_model(),
        "soft_planner_model": ModelConfigService.get_soft_planner_model(),
        "study_model": ModelConfigService.get_study_model(),
        "cache_mode": ModelConfigService.get_cache_mode(),
        "max_function_result_chars": ModelConfigService.get_max_function_result_chars(),
        "call_voice": ModelConfigService.get_call_voice(),
        "call_voice_options": ModelConfigService.get_call_voice_options(),
        **CodexAuthService.settings_payload(),
    }


@router.get("/settings/call_voice_preview")
def preview_call_voice(request, voice: str):
    normalized_voice = str(voice).lower()
    if normalized_voice not in ModelConfigService.CALL_VOICES:
        raise HttpError(400, "Unsupported Corv voice")
    if not corv_settings.openai_key:
        raise HttpError(500, "OpenAI key not configured")
    try:
        response = httpx.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {corv_settings.openai_key}"},
            json={
                "model": "gpt-4o-mini-tts",
                "voice": normalized_voice,
                "input": "Hello, I am Corv. This is how I will sound during your calls.",
                "response_format": "mp3",
            },
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.exception("Call voice preview failed voice=%s", normalized_voice)
        raise HttpError(502, f"Voice preview failed: {exc}")
    return {
        "voice": normalized_voice,
        "content_type": "audio/mpeg",
        "audio_base64": base64.b64encode(response.content).decode("ascii"),
    }


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone=timezone.utc)
        return dt
    except Exception:
        return None


@router.get("/calendar/combined")
def calendar_combined(
    request,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 250,
    days: int = 14,
):
    """
    Return combined hard calendar events and soft event slots for a window.
    Defaults to next 14 days if no time_min/time_max provided.
    """
    now = timezone.now()
    start = _parse_dt(time_min) or now
    end = _parse_dt(time_max) or (now + timedelta(days=days))

    try:
        hard_resp = list_events(
            time_min=start.isoformat(),
            time_max=end.isoformat(),
            max_results=max_results,
        )
        hard_events = hard_resp.get("events", [])
    except Exception as exc:
        raise HttpError(502, f"Failed to fetch calendar events: {exc}")

    slot_qs = SoftEventSlot.objects.select_related("soft_event").filter(
        start_at__lt=end, end_at__gt=start
    ).exclude(status=SoftEventSlot.STATUS_CANCELED)
    soft_slots = []
    for slot in slot_qs:
        soft_slots.append(
            {
                "id": str(slot.id),
                "soft_event_id": str(slot.soft_event_id),
                "title": slot.soft_event.title,
                "start": slot.start_at.isoformat(),
                "end": slot.end_at.isoformat(),
                "status": slot.status,
                "rationale": slot.rationale,
                "deferral_count": slot.deferral_count,
                "promoted": slot.status == SoftEventSlot.STATUS_PROMOTED,
                "soft_deadline": slot.soft_event.soft_deadline.isoformat()
                if slot.soft_event.soft_deadline
                else None,
                "hard_deadline": slot.soft_event.hard_deadline.isoformat()
                if slot.soft_event.hard_deadline
                else None,
            }
        )

    unscheduled = []
    for se in SoftEvent.objects.filter(status=SoftEvent.STATUS_ACTIVE):
        has_future_slot = slot_qs.filter(soft_event=se).exists()
        if not has_future_slot:
            unscheduled.append(
                {
                    "id": str(se.id),
                    "title": se.title,
                    "priority": se.priority,
                    "soft_deadline": se.soft_deadline.isoformat() if se.soft_deadline else None,
                    "hard_deadline": se.hard_deadline.isoformat() if se.hard_deadline else None,
                }
            )

    mapped_hard = []
    hard_links_by_event, _hard_links_by_task = ObjectiveService._matched_hard_event_links(start, end, hard_events=hard_events)
    for ev in hard_events:
        event_key = ObjectiveService._hard_event_match_key(ev.get("id"), ev.get("start"), ev.get("end"))
        mapped_hard.append(
            {
                "id": ev.get("id"),
                "title": ev.get("summary") or "(no title)",
                "description": ev.get("description") or "",
                "start": ev.get("start"),
                "end": ev.get("end"),
                "all_day": ev.get("all_day", False),
                "location": ev.get("location") or "",
                "source": "hard",
                "task_links": [
                    HardEventTaskLinkOut.from_model(link).dict()
                    for link in hard_links_by_event.get(event_key, [])
                ],
            }
        )

    return {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "hard_events": mapped_hard,
        "soft_slots": soft_slots,
        "soft_events_unscheduled": unscheduled,
        "objective_coverage": ObjectiveService.coverage_snapshot(start, end, hard_events=hard_events),
    }


@router.post("/calendar/replan", response=JobOut)
def calendar_replan(request, days: int = 14, note: Optional[str] = None):
    body_payload = _request_json_dict(request)
    days = int(body_payload.get("days", days) or 14)
    note = body_payload.get("note", note)
    module = ToolModule.objects.filter(slug="soft_events").first()
    job = JobService.create_job(
        module=module,
        user_visible_summary="Queued calendar replan",
    )
    job.metadata = {
        **(job.metadata or {}),
        "replan_days": days,
        "replan_note": note,
        "job_kind": "calendar_replan",
    }
    job.save(update_fields=["metadata", "updated_at"])
    try:
        run_calendar_replan_job.delay(str(job.id), days=days, note=note)
    except Exception as exc:
        JobService.mark_status(job, Job.STATUS_FAILED, error_summary=str(exc), progress=job.progress)
        job.user_visible_summary = "Failed to queue calendar replan"
        job.save(update_fields=["user_visible_summary", "updated_at"])
    return JobOut.from_model(job)


@router.get("/objectives/roots", response=List[ObjectiveOut])
def list_objective_roots(request):
    roots = (
        Objective.objects.filter(parent__isnull=True)
        .prefetch_related("tasks", "logs", "children")
        .order_by("deadline_at", "-priority", "created_at")
    )
    return [ObjectiveOut.from_model(objective, include_children=False) for objective in roots]


@router.get("/objective_tasks", response=List[ObjectiveTaskPickerOut])
def list_objective_tasks(
    request,
    include_completed: bool = False,
    due_within_days: Optional[int] = None,
):
    qs = ObjectiveTask.objects.select_related("objective").filter(objective__status=Objective.STATUS_ACTIVE)
    if not include_completed:
        qs = qs.exclude(status__in=[ObjectiveTask.STATUS_DONE, ObjectiveTask.STATUS_CANCELED, ObjectiveTask.STATUS_BLOCKED])
    if due_within_days and due_within_days > 0:
        qs = qs.filter(due_at__isnull=False, due_at__lte=timezone.now() + timedelta(days=due_within_days))
    qs = qs.order_by("due_at", "objective__title", "sort_order", "created_at")
    return [ObjectiveTaskPickerOut.from_model(task) for task in qs[:300]]


@router.get("/objectives/tree/{objective_id}", response=ObjectiveOut)
def get_objective_tree(request, objective_id: UUID):
    try:
        objective = Objective.objects.prefetch_related(
            "tasks",
            "logs",
            "children__tasks",
            "children__logs",
            "children__children",
        ).get(id=objective_id)
    except Objective.DoesNotExist:
        raise HttpError(404, "Objective not found")
    return ObjectiveOut.from_model(objective, include_children=True)


@router.get("/objectives/{objective_id}", response=ObjectiveOut)
def get_objective_detail(request, objective_id: UUID):
    try:
        objective = Objective.objects.prefetch_related("tasks", "logs", "children").get(id=objective_id)
    except Objective.DoesNotExist:
        raise HttpError(404, "Objective not found")
    return ObjectiveOut.from_model(objective, include_children=False)


@router.post("/objectives", response=ObjectiveOut)
def create_objective(request):
    payload = _request_json_dict(request)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HttpError(400, "title is required")
    parent = None
    parent_id = str(payload.get("parent_id") or "").strip()
    if parent_id:
        parent = Objective.objects.filter(id=parent_id).first()
        if parent is None:
            raise HttpError(404, "Parent objective not found")
    deadline_at = _parse_dt(payload.get("deadline_at")) if payload.get("deadline_at") else None
    status = str(payload.get("status") or Objective.STATUS_ACTIVE)
    if status not in dict(Objective.STATUS_CHOICES):
        raise HttpError(400, "Invalid objective status")
    objective = Objective.objects.create(
        parent=parent,
        title=title,
        description=str(payload.get("description") or ""),
        status=status,
        deadline_at=deadline_at,
        estimated_effort_minutes=payload.get("estimated_effort_minutes"),
        remaining_effort_minutes=payload.get("remaining_effort_minutes"),
        priority=int(payload.get("priority") or 0),
        notes=str(payload.get("notes") or ""),
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        chat=parent.chat if parent else None,
    )
    return ObjectiveOut.from_model(objective)


@router.patch("/objectives/{objective_id}", response=ObjectiveOut)
def update_objective(request, objective_id: UUID):
    try:
        objective = Objective.objects.prefetch_related("tasks", "logs", "children").get(id=objective_id)
    except Objective.DoesNotExist:
        raise HttpError(404, "Objective not found")
    payload = _request_json_dict(request)
    updates: list[str] = []
    if "parent_id" in payload:
        parent_id = str(payload.get("parent_id") or "").strip()
        if parent_id:
            parent = Objective.objects.filter(id=parent_id).first()
            if parent is None:
                raise HttpError(404, "Parent objective not found")
            if parent.id == objective.id:
                raise HttpError(400, "An objective cannot be its own parent")
            cursor = parent
            while cursor.parent_id:
                if cursor.parent_id == objective.id:
                    raise HttpError(400, "An objective cannot be moved below one of its descendants")
                cursor = cursor.parent
            objective.parent = parent
        else:
            objective.parent = None
        updates.append("parent")
    if "title" in payload and not str(payload.get("title") or "").strip():
        raise HttpError(400, "title is required")
    if "status" in payload and str(payload.get("status") or "") not in dict(Objective.STATUS_CHOICES):
        raise HttpError(400, "Invalid objective status")
    for key in ["title", "description", "status", "notes"]:
        if key in payload:
            setattr(objective, key, str(payload.get(key) or ""))
            updates.append(key)
    if "deadline_at" in payload:
        objective.deadline_at = _parse_dt(payload.get("deadline_at")) if payload.get("deadline_at") else None
        updates.append("deadline_at")
    for key in ["estimated_effort_minutes", "remaining_effort_minutes", "priority"]:
        if key in payload:
            value = payload.get(key)
            setattr(objective, key, int(value) if value not in (None, "") else None if key != "priority" else 0)
            updates.append(key)
    if "metadata" in payload and isinstance(payload.get("metadata"), dict):
        objective.metadata = payload.get("metadata")
        updates.append("metadata")
    if "status" in payload:
        objective.completed_at = timezone.now() if objective.status == Objective.STATUS_COMPLETED else None
        updates.append("completed_at")
    if updates:
        objective.save(update_fields=list(dict.fromkeys(updates + ["updated_at"])))
    return ObjectiveOut.from_model(objective)


@router.delete("/objectives/{objective_id}")
def delete_objective(request, objective_id: UUID):
    try:
        objective = Objective.objects.get(id=objective_id)
    except Objective.DoesNotExist:
        raise HttpError(404, "Objective not found")
    tree_ids = [objective.id]
    frontier = [objective.id]
    while frontier:
        children = list(Objective.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
        tree_ids.extend(children)
        frontier = children
    generated_soft_events = SoftEvent.objects.filter(
        objective_links__objective_id__in=tree_ids,
        metadata__source=ObjectiveService.OBJECTIVE_SOFT_EVENT_SOURCE,
    ).distinct()
    generated_count = generated_soft_events.count()
    task_count = ObjectiveTask.objects.filter(objective_id__in=tree_ids).count()
    with transaction.atomic():
        generated_soft_events.delete()
        objective.delete()
    return {
        "ok": True,
        "deleted_objectives": len(tree_ids),
        "deleted_tasks": task_count,
        "deleted_generated_sessions": generated_count,
    }


@router.post("/objectives/{objective_id}/tasks", response=ObjectiveTaskOut)
def create_objective_task(request, objective_id: UUID):
    objective = Objective.objects.filter(id=objective_id).first()
    if objective is None:
        raise HttpError(404, "Objective not found")
    payload = _request_json_dict(request)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HttpError(400, "title is required")
    status = str(payload.get("status") or ObjectiveTask.STATUS_TODO)
    if status not in dict(ObjectiveTask.STATUS_CHOICES):
        raise HttpError(400, "Invalid objective task status")
    task = ObjectiveTask.objects.create(
        objective=objective,
        title=title,
        description=str(payload.get("description") or ""),
        status=status,
        estimated_effort_minutes=payload.get("estimated_effort_minutes"),
        remaining_effort_minutes=payload.get("remaining_effort_minutes"),
        due_at=_parse_dt(payload.get("due_at")) if payload.get("due_at") else None,
        sort_order=int(payload.get("sort_order") or 0),
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )
    return ObjectiveTaskOut.from_model(task)


@router.patch("/objective_tasks/{task_id}", response=ObjectiveTaskOut)
def update_objective_task(request, task_id: UUID):
    try:
        task = ObjectiveTask.objects.get(id=task_id)
    except ObjectiveTask.DoesNotExist:
        raise HttpError(404, "Objective task not found")
    payload = _request_json_dict(request)
    updates: list[str] = []
    if "objective_id" in payload:
        objective = Objective.objects.filter(id=payload.get("objective_id")).first()
        if objective is None:
            raise HttpError(404, "Destination objective not found")
        task.objective = objective
        updates.append("objective")
    if "title" in payload and not str(payload.get("title") or "").strip():
        raise HttpError(400, "title is required")
    if "status" in payload and str(payload.get("status") or "") not in dict(ObjectiveTask.STATUS_CHOICES):
        raise HttpError(400, "Invalid objective task status")
    for key in ["title", "description", "status"]:
        if key in payload:
            setattr(task, key, str(payload.get(key) or ""))
            updates.append(key)
    for key in ["estimated_effort_minutes", "remaining_effort_minutes", "sort_order"]:
        if key in payload:
            value = payload.get(key)
            setattr(task, key, int(value) if value not in (None, "") else None)
            updates.append(key)
    if "due_at" in payload:
        task.due_at = _parse_dt(payload.get("due_at")) if payload.get("due_at") else None
        updates.append("due_at")
    if "metadata" in payload and isinstance(payload.get("metadata"), dict):
        task.metadata = payload.get("metadata")
        updates.append("metadata")
    if "status" in payload:
        task.completed_at = timezone.now() if task.status == ObjectiveTask.STATUS_DONE else None
        updates.append("completed_at")
    if updates:
        task.save(update_fields=list(dict.fromkeys(updates + ["updated_at"])))
    return ObjectiveTaskOut.from_model(task)


@router.delete("/objective_tasks/{task_id}")
def delete_objective_task(request, task_id: UUID):
    deleted, _ = ObjectiveTask.objects.filter(id=task_id).delete()
    if not deleted:
        raise HttpError(404, "Objective task not found")
    return {"ok": True}


@router.post("/calendar/hard_event_task_links", response=HardEventTaskLinkOut)
def create_hard_event_task_link(request):
    payload = _request_json_dict(request)
    task_id = str(payload.get("task_id") or "").strip()
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    if not task_id:
        raise HttpError(400, "task_id is required")
    event_id = str(event.get("id") or "").strip()
    event_start_raw = str(event.get("start") or "").strip()
    event_end_raw = str(event.get("end") or "").strip()
    if not event_id or not event_start_raw or not event_end_raw:
        raise HttpError(400, "event id/start/end are required")
    try:
        task = ObjectiveTask.objects.select_related("objective").get(id=task_id)
    except ObjectiveTask.DoesNotExist:
        raise HttpError(404, "Objective task not found")
    event_start_at = _parse_dt(event_start_raw)
    event_end_at = _parse_dt(event_end_raw)
    if not event_start_at or not event_end_at or event_end_at <= event_start_at:
        raise HttpError(400, "Invalid event timing")
    link, _created = HardEventTaskLink.objects.update_or_create(
        task=task,
        event_id=event_id,
        event_start_raw=event_start_raw,
        event_end_raw=event_end_raw,
        defaults={
            "event_title": str(event.get("title") or event.get("summary") or "")[:255],
            "event_start_at": event_start_at,
            "event_end_at": event_end_at,
            "all_day": bool(event.get("all_day")),
            "description": str(event.get("description") or ""),
            "location": str(event.get("location") or "")[:255],
            "source": str(event.get("source") or "google_calendar")[:64],
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        },
    )
    return HardEventTaskLinkOut.from_model(link)


@router.delete("/calendar/hard_event_task_links/{link_id}")
def delete_hard_event_task_link(request, link_id: UUID):
    deleted, _ = HardEventTaskLink.objects.filter(id=link_id).delete()
    if not deleted:
        raise HttpError(404, "Hard-event task link not found")
    return {"ok": True}


@router.get("/objectives/{objective_id}/logs", response=List[ObjectiveLogOut])
def list_objective_logs(request, objective_id: UUID):
    logs = ObjectiveLog.objects.filter(objective_id=objective_id).order_by("-logged_at", "-created_at")
    return [ObjectiveLogOut.from_model(log) for log in logs]


@router.post("/objectives/{objective_id}/logs", response=ObjectiveLogOut)
def create_objective_log(request, objective_id: UUID):
    objective = Objective.objects.filter(id=objective_id).first()
    if objective is None:
        raise HttpError(404, "Objective not found")
    payload = _request_json_dict(request)
    log = ObjectiveLog.objects.create(
        objective=objective,
        task_id=payload.get("task_id"),
        kind=str(payload.get("kind") or ObjectiveLog.KIND_NOTE),
        text=str(payload.get("text") or ""),
        minutes_spent=payload.get("minutes_spent"),
        logged_at=_parse_dt(payload.get("logged_at")) if payload.get("logged_at") else timezone.now(),
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )
    return ObjectiveLogOut.from_model(log)


@router.patch("/objective_logs/{log_id}", response=ObjectiveLogOut)
def update_objective_log(request, log_id: UUID):
    try:
        log = ObjectiveLog.objects.get(id=log_id)
    except ObjectiveLog.DoesNotExist:
        raise HttpError(404, "Objective log not found")
    payload = _request_json_dict(request)
    updates: list[str] = []
    for key in ["kind", "text"]:
        if key in payload:
            setattr(log, key, str(payload.get(key) or ""))
            updates.append(key)
    if "minutes_spent" in payload:
        log.minutes_spent = int(payload.get("minutes_spent")) if payload.get("minutes_spent") not in (None, "") else None
        updates.append("minutes_spent")
    if "task_id" in payload:
        log.task_id = payload.get("task_id") or None
        updates.append("task")
    if "logged_at" in payload:
        log.logged_at = _parse_dt(payload.get("logged_at")) if payload.get("logged_at") else timezone.now()
        updates.append("logged_at")
    if "metadata" in payload and isinstance(payload.get("metadata"), dict):
        log.metadata = payload.get("metadata")
        updates.append("metadata")
    if updates:
        log.save(update_fields=list(dict.fromkeys(updates)))
    return ObjectiveLogOut.from_model(log)


@router.delete("/objective_logs/{log_id}")
def delete_objective_log(request, log_id: UUID):
    deleted, _ = ObjectiveLog.objects.filter(id=log_id).delete()
    if not deleted:
        raise HttpError(404, "Objective log not found")
    return {"ok": True}


@router.get("/soft_events/{soft_event_id}")
def get_soft_event_detail(request, soft_event_id: UUID):
    try:
        se = SoftEvent.objects.get(id=soft_event_id)
    except SoftEvent.DoesNotExist:
        raise HttpError(404, "Soft event not found")
    linked_tasks = [
        {
            "task_id": str(link.task_id),
            "task_title": link.task.title,
            "objective_id": str(link.task.objective_id),
            "objective_title": link.task.objective.title,
            "due_at": link.task.due_at.isoformat() if link.task.due_at else None,
            "status": link.task.status,
        }
        for link in SoftEventTask.objects.filter(soft_event=se).select_related("task__objective").order_by(
            "task__objective__title", "task__sort_order", "task__created_at"
        )
    ]
    return {
        "id": str(se.id),
        "title": se.title,
        "description": se.description,
        "notes": se.notes,
        "preferred_duration_minutes": se.preferred_duration_minutes,
        "min_duration_minutes": se.min_duration_minutes,
        "soft_deadline": se.soft_deadline.isoformat() if se.soft_deadline else None,
        "hard_deadline": se.hard_deadline.isoformat() if se.hard_deadline else None,
        "frequency": se.frequency,
        "deferral_limit": se.deferral_limit,
        "priority": se.priority,
        "status": se.status,
        "metadata": se.metadata or {},
        "linked_tasks": linked_tasks,
    }


@router.patch("/soft_events/{soft_event_id}")
def update_soft_event_detail(
    request,
    soft_event_id: UUID,
    title: Optional[str] = None,
    description: Optional[str] = None,
    notes: Optional[str] = None,
    preferred_duration_minutes: Optional[int] = None,
    min_duration_minutes: Optional[int] = None,
    soft_deadline: Optional[str] = None,
    hard_deadline: Optional[str] = None,
    frequency: Optional[str] = None,
    deferral_limit: Optional[int] = None,
    priority: Optional[int] = None,
    status: Optional[str] = None,
    duration_minutes: Optional[int] = None,
):
    try:
        se = SoftEvent.objects.get(id=soft_event_id)
    except SoftEvent.DoesNotExist:
        raise HttpError(404, "Soft event not found")

    body_payload = {}
    try:
        if getattr(request, "body", None):
            parsed = json.loads(request.body.decode("utf-8"))
            if isinstance(parsed, dict):
                body_payload = parsed
    except Exception:
        body_payload = {}

    title = body_payload.get("title", title)
    description = body_payload.get("description", description)
    notes = body_payload.get("notes", notes)
    preferred_duration_minutes = body_payload.get("preferred_duration_minutes", preferred_duration_minutes)
    min_duration_minutes = body_payload.get("min_duration_minutes", min_duration_minutes)
    soft_deadline = body_payload.get("soft_deadline", soft_deadline)
    hard_deadline = body_payload.get("hard_deadline", hard_deadline)
    frequency = body_payload.get("frequency", frequency)
    deferral_limit = body_payload.get("deferral_limit", deferral_limit)
    priority = body_payload.get("priority", priority)
    status = body_payload.get("status", status)
    duration_minutes = body_payload.get("duration_minutes", duration_minutes)

    fields = []
    if title is not None:
        se.title = title
        fields.append("title")
    if description is not None:
        se.description = description
        fields.append("description")
    if notes is not None:
        se.notes = notes
        fields.append("notes")
    # Backward compatibility for old clients sending a single duration field.
    if duration_minutes is not None and preferred_duration_minutes is None:
        preferred_duration_minutes = duration_minutes
    if preferred_duration_minutes is not None:
        se.preferred_duration_minutes = max(int(preferred_duration_minutes), 1)
        fields.append("preferred_duration_minutes")
    if min_duration_minutes is not None:
        se.min_duration_minutes = max(int(min_duration_minutes), 1)
        fields.append("min_duration_minutes")
    if preferred_duration_minutes is not None and min_duration_minutes is None:
        se.min_duration_minutes = min(se.min_duration_minutes, se.preferred_duration_minutes)
        fields.append("min_duration_minutes")
    if min_duration_minutes is not None and preferred_duration_minutes is None:
        se.preferred_duration_minutes = max(se.preferred_duration_minutes, se.min_duration_minutes)
        fields.append("preferred_duration_minutes")
    if soft_deadline is not None:
        se.soft_deadline = _parse_dt(soft_deadline) if soft_deadline else None
        fields.append("soft_deadline")
    if hard_deadline is not None:
        se.hard_deadline = _parse_dt(hard_deadline) if hard_deadline else None
        fields.append("hard_deadline")
    if frequency is not None:
        se.frequency = frequency
        fields.append("frequency")
    if deferral_limit is not None:
        se.deferral_limit = max(int(deferral_limit), 0)
        fields.append("deferral_limit")
    if priority is not None:
        se.priority = int(priority)
        fields.append("priority")
    if status is not None:
        se.status = status
        fields.append("status")
    if fields:
        se.save(update_fields=list(set(fields + ["updated_at"])))

    return {
        "id": str(se.id),
        "title": se.title,
        "description": se.description,
        "notes": se.notes,
        "preferred_duration_minutes": se.preferred_duration_minutes,
        "min_duration_minutes": se.min_duration_minutes,
        "soft_deadline": se.soft_deadline.isoformat() if se.soft_deadline else None,
        "hard_deadline": se.hard_deadline.isoformat() if se.hard_deadline else None,
        "frequency": se.frequency,
        "deferral_limit": se.deferral_limit,
        "priority": se.priority,
        "status": se.status,
        "metadata": se.metadata or {},
    }


@router.post("/soft_events")
def create_soft_event_detail(
    request,
    title: str,
    description: str = "",
    notes: str = "",
    preferred_duration_minutes: int = 60,
    min_duration_minutes: int = 30,
    soft_deadline: Optional[str] = None,
    hard_deadline: Optional[str] = None,
    frequency: str = "",
    deferral_limit: int = 3,
    priority: int = 0,
    duration_minutes: Optional[int] = None,
):
    body_payload = {}
    try:
        if getattr(request, "body", None):
            parsed = json.loads(request.body.decode("utf-8"))
            if isinstance(parsed, dict):
                body_payload = parsed
    except Exception:
        body_payload = {}

    title = body_payload.get("title", title)
    description = body_payload.get("description", description)
    notes = body_payload.get("notes", notes)
    preferred_duration_minutes = body_payload.get("preferred_duration_minutes", preferred_duration_minutes)
    min_duration_minutes = body_payload.get("min_duration_minutes", min_duration_minutes)
    soft_deadline = body_payload.get("soft_deadline", soft_deadline)
    hard_deadline = body_payload.get("hard_deadline", hard_deadline)
    frequency = body_payload.get("frequency", frequency)
    deferral_limit = body_payload.get("deferral_limit", deferral_limit)
    priority = body_payload.get("priority", priority)
    duration_minutes = body_payload.get("duration_minutes", duration_minutes)

    # Backward compatibility for old clients sending a single duration field.
    if duration_minutes is not None and "preferred_duration_minutes" not in body_payload:
        preferred_duration_minutes = duration_minutes

    preferred_duration_minutes = max(int(preferred_duration_minutes or 0), 1)
    min_duration_minutes = max(int(min_duration_minutes or 0), 1)
    if min_duration_minutes > preferred_duration_minutes:
        preferred_duration_minutes = min_duration_minutes

    se = SoftEvent.objects.create(
        title=title,
        description=description or "",
        notes=notes or "",
        preferred_duration_minutes=preferred_duration_minutes,
        min_duration_minutes=min_duration_minutes,
        soft_deadline=_parse_dt(soft_deadline) if soft_deadline else None,
        hard_deadline=_parse_dt(hard_deadline) if hard_deadline else None,
        frequency=frequency or "",
        deferral_limit=max(deferral_limit or 0, 0),
        priority=priority or 0,
        status=SoftEvent.STATUS_ACTIVE,
    )
    return {
        "id": str(se.id),
        "title": se.title,
        "description": se.description,
        "notes": se.notes,
        "preferred_duration_minutes": se.preferred_duration_minutes,
        "min_duration_minutes": se.min_duration_minutes,
        "soft_deadline": se.soft_deadline.isoformat() if se.soft_deadline else None,
        "hard_deadline": se.hard_deadline.isoformat() if se.hard_deadline else None,
        "frequency": se.frequency,
        "deferral_limit": se.deferral_limit,
        "priority": se.priority,
        "status": se.status,
        "metadata": se.metadata or {},
    }


@router.post("/soft_slots/{slot_id}/promote")
def promote_soft_slot(request, slot_id: UUID):
    result = soft_events.promote_slot(slot_id=str(slot_id))
    return result


@router.delete("/soft_events/{soft_event_id}")
def delete_soft_event_route(request, soft_event_id: UUID):
    return calendar_manager.delete_soft_event(soft_event_id=str(soft_event_id))


@router.post("/soft_slots/{slot_id}/outcome")
def mark_soft_slot_outcome(request, slot_id: UUID):
    payload = _request_json_dict(request)
    outcome = str(payload.get("outcome") or "").strip()
    if not outcome:
        raise HttpError(400, "outcome is required")
    reason = str(payload.get("reason") or "")
    minutes_spent = payload.get("minutes_spent")
    if minutes_spent not in (None, ""):
        try:
            minutes_spent = int(minutes_spent)
        except (TypeError, ValueError):
            raise HttpError(400, "minutes_spent must be an integer")
    else:
        minutes_spent = None
    completed_task_ids = payload.get("completed_task_ids")
    if completed_task_ids is not None and not isinstance(completed_task_ids, list):
        raise HttpError(400, "completed_task_ids must be a list")
    result = soft_events.mark_slot_outcome(
        slot_id=str(slot_id),
        outcome=outcome,
        reason=reason,
        minutes_spent=minutes_spent,
        completed_task_ids=[str(item) for item in (completed_task_ids or []) if str(item).strip()],
    )
    return result
