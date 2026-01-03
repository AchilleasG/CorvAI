from __future__ import annotations

import logging

from celery import shared_task

from django.core.management import call_command

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
