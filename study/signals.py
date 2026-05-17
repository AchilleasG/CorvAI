from __future__ import annotations

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from study.models import StudyTopic
from study.services import StudyPlannerService


@receiver(pre_delete, sender=StudyTopic)
def cleanup_topic_soft_events_on_delete(sender, instance: StudyTopic, **kwargs):
    StudyPlannerService.cleanup_topic_soft_events(instance)
