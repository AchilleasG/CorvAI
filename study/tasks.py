from __future__ import annotations

import logging

from celery import shared_task

from study.services import AssignmentProcessingJobService, StudyProcessingJobService
from study.services import StudyTopicAudiobookService

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


@shared_task(name="study.tasks.process_study_assignment_job")
def process_study_assignment_job(
    job_id: str,
    assignment_id: str,
    uploaded_file_path: str | None = None,
    requested_session_count: int | None = None,
):
    try:
        AssignmentProcessingJobService.run_assignment_processing_job(
            job_id,
            assignment_id,
            uploaded_file_path=uploaded_file_path,
            requested_session_count=requested_session_count,
        )
        return {"job_id": job_id, "assignment_id": assignment_id, "status": "completed"}
    except Exception as exc:
        logger.exception("Study assignment job failed for %s: %s", assignment_id, exc)
        raise


@shared_task(name="study.tasks.generate_study_topic_audiobook_job")
def generate_study_topic_audiobook_job(
    job_id: str,
    topic_id: str,
    version_id: str,
    model: str | None = None,
    voice: str = "alloy",
):
    try:
        StudyTopicAudiobookService.run_audiobook_generation_job(
            job_id,
            topic_id,
            version_id,
            model=model,
            voice=voice,
        )
        return {
            "job_id": job_id,
            "topic_id": topic_id,
            "version_id": version_id,
            "status": "completed",
        }
    except Exception as exc:
        logger.exception("Study topic audiobook job failed for %s: %s", topic_id, exc)
        raise