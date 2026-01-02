from typing import List, Optional
from uuid import UUID
from ninja import Router
from ninja.errors import HttpError

from django.db.models import Sum
from datetime import timedelta
from django.utils import timezone

from orchestration.api_schemas import JobOut
from orchestration.models import Job, UsageEvent
from orchestration.services import JobService, ModelConfigService
from chat.models import ChatMessage
from chat.schemas import MessageOut

router = Router(tags=["orchestration"])


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
