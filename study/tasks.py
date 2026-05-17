from __future__ import annotations

import logging

from celery import shared_task

from study.services import StudyProcessingJobService

logger = logging.getLogger(__name__)


@shared_task(name="study.tasks.process_study_material_job")
def process_study_material_job(job_id: str, material_id: str, model: str | None = None, max_pages: int | None = None):
    try:
        StudyProcessingJobService.run_material_processing_job(
            job_id,
            material_id,
            model=model,
            max_pages=max_pages,
        )
        return {"job_id": job_id, "material_id": material_id, "status": "completed"}
    except Exception as exc:
        logger.exception("Study material job failed for %s: %s", material_id, exc)
        raise