from __future__ import annotations

import logging

from celery import shared_task

from django.core.management import call_command

from orchestration.scheduler import poll_due_tasks
from orchestration.call_processing import poll_call_sessions
from orchestration.tools.soft_events import SoftPlannerJobService

logger = logging.getLogger(__name__)


@shared_task(name="orchestration.tasks.cleanup_expired_notes")
def cleanup_expired_notes_task():
    from orchestration.services import UserInfoService
    deleted = UserInfoService.cleanup_expired_notes()
    if deleted:
        logger.info("Soft-deleted %s expired timed note(s)", deleted)
    return {"deleted": deleted}


@shared_task(name="orchestration.tasks.poll_soft_events_task")
def poll_soft_events_task():
    """
    Run the poll_soft_events management command (used by Celery beat every 5 minutes).
    """
    try:
        call_command("poll_soft_events")
    except Exception as exc:
        logger.exception("poll_soft_events failed: %s", exc)
        raise


@shared_task(name="orchestration.tasks.poll_scheduled_tasks")
def poll_scheduled_tasks():
    """
    Execute due scheduled tasks from the DB (used by Celery beat every minute).
    """
    try:
        return poll_due_tasks()
    except Exception as exc:
        logger.exception("poll_scheduled_tasks failed: %s", exc)
        raise


@shared_task(name="orchestration.tasks.poll_call_sessions")
def poll_call_sessions_task():
    """
    Check scheduled/ringing call sessions and dispatch notifications.
    """
    try:
        return poll_call_sessions()
    except Exception as exc:
        logger.exception("poll_call_sessions failed: %s", exc)
        raise


@shared_task(name="orchestration.tasks.poll_soft_event_slots_task")
def poll_soft_event_slots_task():
    """
    Poll for soft event slots due within ±5 minutes and make calls (used by Celery beat every 5 minutes).
    """
    try:
        call_command("poll_soft_event_slots")
    except Exception as exc:
        logger.exception("poll_soft_event_slots failed: %s", exc)
        raise


@shared_task(name="orchestration.tasks.run_calendar_replan_job")
def run_calendar_replan_job(job_id: str, days: int = 14, note: str | None = None):
    try:
        result = SoftPlannerJobService.run_replan_job(job_id, days=days, note=note)
        return {"job_id": job_id, "status": "completed", "result": result}
    except Exception as exc:
        logger.exception("Calendar replan job failed for %s: %s", job_id, exc)
        raise
