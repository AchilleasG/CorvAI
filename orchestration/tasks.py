from __future__ import annotations

import logging

from celery import shared_task

from django.core.management import call_command

from orchestration.scheduler import poll_due_tasks

logger = logging.getLogger(__name__)


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
