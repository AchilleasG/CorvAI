from typing import List, Optional
from uuid import UUID
from ninja import Router
from ninja.errors import HttpError

from orchestration.api_schemas import JobOut
from orchestration.models import Job

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
