from __future__ import annotations

import os

from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from study.models import StudyAssignment, StudyCourse, StudyTopic
from study.services import AssignmentService, StudyPlannerService


@receiver(pre_delete, sender=StudyTopic)
def cleanup_topic_soft_events_on_delete(sender, instance: StudyTopic, **kwargs):
    StudyPlannerService.cleanup_topic_soft_events(instance)


@receiver(pre_delete, sender=StudyAssignment)
def cleanup_assignment_resources_on_delete(sender, instance: StudyAssignment, **kwargs):
    AssignmentService.cleanup_assignment_soft_events(instance)
    uploaded_file = getattr(instance, "uploaded_file", None)
    if uploaded_file:
        try:
            uploaded_file.delete(save=False)
        except Exception:
            pass
    file_path = AssignmentService.uploaded_file_path(instance)
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            # Best-effort file cleanup to avoid breaking assignment deletion.
            pass


def _delete_linked_objective(instance) -> None:
    objective_id = getattr(instance, "objective_id", None)
    if not objective_id:
        return
    try:
        instance.objective.delete()
    except Exception:
        pass


@receiver(post_delete, sender=StudyCourse)
def cleanup_course_objective_on_delete(sender, instance: StudyCourse, **kwargs):
    _delete_linked_objective(instance)


@receiver(post_delete, sender=StudyTopic)
def cleanup_topic_objective_on_delete(sender, instance: StudyTopic, **kwargs):
    _delete_linked_objective(instance)


@receiver(post_delete, sender=StudyAssignment)
def cleanup_assignment_objective_on_delete(sender, instance: StudyAssignment, **kwargs):
    _delete_linked_objective(instance)
