from __future__ import annotations

from typing import Optional
from uuid import UUID
from ninja import Schema
from orchestration.models import Job


class JobOut(Schema):
    id: UUID
    status: str
    user_visible_summary: str
    progress: float
    module_slug: Optional[str] = None
    active_function: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @staticmethod
    def from_model(job: Job) -> "JobOut":
        return JobOut(
            id=job.id,
            status=job.status,
            user_visible_summary=job.user_visible_summary or "",
            progress=job.progress,
            module_slug=job.module.slug if job.module else None,
            active_function=job.active_function.manifest_id if job.active_function else None,
            created_at=job.created_at.isoformat() if job.created_at else None,
            updated_at=job.updated_at.isoformat() if job.updated_at else None,
        )
