from typing import List, Optional
import logging
from uuid import UUID
from ninja import Router
from ninja.errors import HttpError

from django.db.models import Sum
from datetime import timedelta
from django.utils import timezone
from datetime import datetime

from orchestration.api_schemas import (
    JobOut,
    ScheduledTaskOut,
    ScheduledTaskRunOut,
    ScheduledTaskLogOut,
    PushTokenOut,
    UserMessageOut,
    CallSessionOut,
    CallTranscriptEntryOut,
)
from orchestration.models import (
    Job,
    UsageEvent,
    SoftEvent,
    SoftEventSlot,
    ScheduledTask,
    ScheduledTaskRun,
    ScheduledTaskLogEntry,
    PushToken,
    UserMessage,
    CallSession,
    CallTranscriptEntry,
)
from orchestration.call_processing import (
    create_call_session,
    accept_call,
    complete_call,
    mark_call_missed,
    should_end_call,
)
from orchestration.notifications import send_call_push_to_all, send_push_to_all
from Corv.config import settings as corv_settings
import httpx
from orchestration.services import JobService, ModelConfigService
from chat.models import ChatMessage
from chat.schemas import MessageOut
from orchestration.tools.calendar import list_events
from orchestration.tools import soft_events

router = Router(tags=["orchestration"])
logger = logging.getLogger(__name__)


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
        "cache_mode": ModelConfigService.get_cache_mode(),
        "max_function_result_chars": ModelConfigService.get_max_function_result_chars(),
    }


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
def list_call_sessions(request, status: Optional[str] = None):
    qs = CallSession.objects.all()
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


@router.post("/call_sessions", response=CallSessionOut)
def create_call(request, goal: str, scheduled_for: Optional[str] = None):
    dt = _parse_dt(scheduled_for) if scheduled_for else None
    session = create_call_session(goal=goal, scheduled_for=dt)
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
    if session.status == CallSession.STATUS_IN_CALL and role == "assistant":
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
    send_call_push_to_all(
        title="Incoming call from Corv",
        body=session.goal[:120],
        data={"call_session_id": str(session.id), "type": "call_incoming"},
    )
    return {"ok": True}


@router.post("/call_sessions/{session_id}/realtime_token")
def create_realtime_token(request, session_id: UUID, model: Optional[str] = None):
    try:
        session = CallSession.objects.get(id=session_id)
    except CallSession.DoesNotExist:
        raise HttpError(404, "Call session not found")

    api_key = corv_settings.openai_key
    if not api_key:
        raise HttpError(500, "OpenAI key not configured")

    model_name = model or "gpt-4o-realtime-preview-2024-12-17"
    payload = {
        "model": model_name,
        "voice": "alloy",
        "instructions": f"Call goal: {session.goal}. Be concise and helpful.",
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                "https://api.openai.com/v1/realtime/sessions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        raise HttpError(502, f"Failed to create realtime session: {exc}")


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
    prompt: Optional[str] = None,
    start_at: Optional[str] = None,
    recurrence: Optional[str] = None,
    status: Optional[str] = None,
):
    try:
        task = ScheduledTask.objects.get(id=task_id)
    except ScheduledTask.DoesNotExist:
        raise HttpError(404, "Scheduled task not found")

    if recurrence and recurrence not in dict(ScheduledTask.RECURRENCE_CHOICES):
        raise HttpError(400, "Invalid recurrence value")
    if status and status not in dict(ScheduledTask.STATUS_CHOICES):
        raise HttpError(400, "Invalid status value")

    if prompt is not None:
        task.prompt = prompt
    if recurrence is not None:
        task.recurrence = recurrence
    if start_at is not None:
        dt = _parse_dt(start_at)
        if not dt:
            raise HttpError(400, "Invalid start_at datetime")
        task.start_at = dt
        task.next_run_at = dt if task.status == ScheduledTask.STATUS_ACTIVE else task.next_run_at
    if status is not None:
        task.status = status
        if status == ScheduledTask.STATUS_ACTIVE and task.next_run_at is None:
            task.next_run_at = task.start_at
        if status != ScheduledTask.STATUS_ACTIVE:
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
    cache_mode: Optional[str] = None,
    max_function_result_chars: Optional[int] = None,
):
    if frontman_model:
        ModelConfigService.set_setting("frontman_model", frontman_model)
    if caller_model:
        ModelConfigService.set_setting("caller_model", caller_model)
    if cache_mode:
        ModelConfigService.set_setting("cache_mode", cache_mode.lower())
    if max_function_result_chars is not None:
        ModelConfigService.set_setting("max_function_result_chars", str(max_function_result_chars))
    return {
        "frontman_model": ModelConfigService.get_frontman_model(),
        "caller_model": ModelConfigService.get_caller_model(),
        "cache_mode": ModelConfigService.get_cache_mode(),
        "max_function_result_chars": ModelConfigService.get_max_function_result_chars(),
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
    for ev in hard_events:
        mapped_hard.append(
            {
                "id": ev.get("id"),
                "title": ev.get("summary") or "(no title)",
                "start": ev.get("start"),
                "end": ev.get("end"),
                "all_day": ev.get("all_day", False),
                "source": "hard",
            }
        )

    return {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "hard_events": mapped_hard,
        "soft_slots": soft_slots,
        "soft_events_unscheduled": unscheduled,
    }


@router.post("/calendar/replan")
def calendar_replan(request, days: int = 14, note: Optional[str] = None):
    result = soft_events.replan_window(days=days, note=note)
    return result


@router.get("/soft_events/{soft_event_id}")
def get_soft_event_detail(request, soft_event_id: UUID):
    try:
        se = SoftEvent.objects.get(id=soft_event_id)
    except SoftEvent.DoesNotExist:
        raise HttpError(404, "Soft event not found")
    return {
        "id": str(se.id),
        "title": se.title,
        "description": se.description,
        "notes": se.notes,
        "duration_minutes": se.duration_minutes,
        "soft_deadline": se.soft_deadline.isoformat() if se.soft_deadline else None,
        "hard_deadline": se.hard_deadline.isoformat() if se.hard_deadline else None,
        "frequency": se.frequency,
        "deferral_limit": se.deferral_limit,
        "priority": se.priority,
        "status": se.status,
    }


@router.patch("/soft_events/{soft_event_id}")
def update_soft_event_detail(
    request,
    soft_event_id: UUID,
    title: Optional[str] = None,
    description: Optional[str] = None,
    notes: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    soft_deadline: Optional[str] = None,
    hard_deadline: Optional[str] = None,
    frequency: Optional[str] = None,
    deferral_limit: Optional[int] = None,
    priority: Optional[int] = None,
    status: Optional[str] = None,
):
    try:
        se = SoftEvent.objects.get(id=soft_event_id)
    except SoftEvent.DoesNotExist:
        raise HttpError(404, "Soft event not found")

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
    if duration_minutes is not None:
        se.duration_minutes = max(int(duration_minutes), 1)
        fields.append("duration_minutes")
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
        "duration_minutes": se.duration_minutes,
        "soft_deadline": se.soft_deadline.isoformat() if se.soft_deadline else None,
        "hard_deadline": se.hard_deadline.isoformat() if se.hard_deadline else None,
        "frequency": se.frequency,
        "deferral_limit": se.deferral_limit,
        "priority": se.priority,
        "status": se.status,
    }


@router.post("/soft_events")
def create_soft_event_detail(
    request,
    title: str,
    description: str = "",
    notes: str = "",
    duration_minutes: int = 30,
    soft_deadline: Optional[str] = None,
    hard_deadline: Optional[str] = None,
    frequency: str = "",
    deferral_limit: int = 3,
    priority: int = 0,
):
    se = SoftEvent.objects.create(
        title=title,
        description=description or "",
        notes=notes or "",
        duration_minutes=max(duration_minutes or 0, 1),
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
        "duration_minutes": se.duration_minutes,
        "soft_deadline": se.soft_deadline.isoformat() if se.soft_deadline else None,
        "hard_deadline": se.hard_deadline.isoformat() if se.hard_deadline else None,
        "frequency": se.frequency,
        "deferral_limit": se.deferral_limit,
        "priority": se.priority,
        "status": se.status,
    }


@router.post("/soft_slots/{slot_id}/promote")
def promote_soft_slot(request, slot_id: UUID):
    result = soft_events.promote_slot(slot_id=str(slot_id))
    return result
