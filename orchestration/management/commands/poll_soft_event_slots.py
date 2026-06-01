from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from orchestration.models import SoftEventSlot
from orchestration.tools.call_sessions import create_session

logger = logging.getLogger(__name__)


def build_study_goal(soft_event, is_single: bool = False) -> str:
    """
    Build a conversational, tutorial-oriented goal for study soft events.
    Instead of just telling them to study, engage them in the material first
    and guide them toward actually doing the homework.
    """
    metadata = soft_event.metadata or {}
    has_homework = metadata.get("study_topic_homework_required", False)
    homework_count = metadata.get("study_topic_homework_count", 0)
    
    parts = []
    
    # Intro: casual engagement
    parts.append(f"Let's work through {soft_event.title}.")
    
    # Content: describe what we'll cover
    if soft_event.description:
        parts.append(f"Here's what we need to cover:\n\n{soft_event.description}")
    
    # Tutoring: guide them through concepts
    parts.append("I'll walk you through the key concepts, and we'll think through some examples together so you really get it.")
    
    # Homework nudge: if there's homework assigned
    if has_homework and homework_count > 0:
        parts.append(f"Then, once you're comfortable, you'll tackle the {homework_count} homework questions assigned to this lesson.")
    else:
        parts.append("Then we'll work through it so you can confidently solve problems on your own.")
    
    # Context from notes
    if soft_event.notes:
        parts.append(f"\nFull context:\n{soft_event.notes}")
    
    return "\n\n".join(parts)


def build_assignment_goal(soft_event) -> str:
    """Build a focused goal for assignment sessions with checklist guidance."""
    metadata = soft_event.metadata or {}
    assignment_title = metadata.get("assignment_title") or soft_event.title
    session_number = metadata.get("session_number")
    total_sessions = metadata.get("total_sessions")
    steps = metadata.get("assignment_checklist_steps") or []

    parts = [f"Let's work on assignment: {assignment_title}."]
    if session_number and total_sessions:
        parts.append(f"This is session {session_number} of {total_sessions}.")
    if soft_event.description:
        parts.append(f"Plan for this session:\n\n{soft_event.description}")

    if isinstance(steps, list) and steps:
        formatted_steps = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            title = str(step.get("title") or "").strip()
            description = str(step.get("description") or "").strip()
            if title and description:
                formatted_steps.append(f"- {title}: {description}")
            elif title:
                formatted_steps.append(f"- {title}")
            elif description:
                formatted_steps.append(f"- {description}")
        if formatted_steps:
            parts.append("Checklist items to cover now:\n" + "\n".join(formatted_steps))

    if soft_event.notes:
        parts.append(f"Context:\n{soft_event.notes}")

    return "\n\n".join(parts)


class Command(BaseCommand):
    help = "Poll soft event slots for those due within ±5 minutes and make calls (run every 5 minutes via Celery beat)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--window-minutes",
            type=int,
            default=5,
            help="Check for slots due within ±N minutes (default 5).",
        )

    def handle(self, *args, **options):
        window_minutes = options.get("window_minutes") or 5
        now = timezone.now()
        start_window = now - timedelta(minutes=window_minutes)
        end_window = now + timedelta(minutes=window_minutes)

        # Find due slots: planned, start in window, not yet called.
        due_slots = list(
            SoftEventSlot.objects.filter(
                status=SoftEventSlot.STATUS_PLANNED,
                start_at__gte=start_window,
                start_at__lte=end_window,
                call_made_at__isnull=True,
            ).select_related("soft_event").order_by("start_at")
        )

        if not due_slots:
            logger.info("poll_soft_event_slots: no due slots in window ±%d minutes", window_minutes)
            return

        try:
            # Build a conversational goal mentioning all due tasks.
            if len(due_slots) == 1:
                slot = due_slots[0]
                se = slot.soft_event
                
                metadata = se.metadata or {}
                source = metadata.get("source")
                is_study = source == "study_session_target"
                is_assignment = source == "study_assignment"
                
                if is_study:
                    goal = build_study_goal(se, is_single=True)
                elif is_assignment:
                    goal = build_assignment_goal(se)
                else:
                    goal = f"Time to do: {se.title}."
                    if se.description:
                        goal = f"{goal} {se.description}"
                    if se.notes:
                        goal = f"{goal} Notes: {se.notes}"
                
                scheduled_for = slot.start_at.isoformat()
            else:
                # Multiple slots: create conversational summary
                goal_lines = ["You have the following tasks coming up. Let's go through them one at a time:\n"]
                has_study_tasks = False
                study_tasks_with_homework = 0
                assignment_steps = []
                
                for i, slot in enumerate(due_slots, 1):
                    se = slot.soft_event
                    metadata = se.metadata or {}
                    source = metadata.get("source")
                    is_study = source == "study_session_target"
                    is_assignment = source == "study_assignment"
                    
                    if is_study:
                        has_study_tasks = True
                        # For study tasks in batch, use title + description + homework note
                        task_desc = f"{i}. {se.title}"
                        if se.description:
                            task_desc = f"{task_desc}: {se.description}"
                        metadata = se.metadata or {}
                        if metadata.get("study_topic_homework_required"):
                            study_tasks_with_homework += 1
                            task_desc = f"{task_desc} [{metadata.get('study_topic_homework_count', 1)} homework question(s)]"
                    else:
                        task_desc = f"{i}. {se.title}"
                        if se.description:
                            task_desc = f"{task_desc}: {se.description}"

                    if is_assignment:
                        checklist_steps = metadata.get("assignment_checklist_steps") or []
                        if isinstance(checklist_steps, list):
                            for step in checklist_steps:
                                if not isinstance(step, dict):
                                    continue
                                label = str(step.get("title") or step.get("description") or "").strip()
                                if label:
                                    assignment_steps.append(label)
                    
                    if se.notes and not is_study:  # Study events have notes in their description, don't duplicate
                        task_desc = f"{task_desc}\n   Notes: {se.notes}"
                    
                    goal_lines.append(task_desc)
                
                goal = "\n".join(goal_lines)
                
                # Add context-specific guidance
                if has_study_tasks and study_tasks_with_homework > 0:
                    goal += "\n\nFor the study topics, I'll walk you through the material conversationally and work through examples together, then you'll tackle the assigned homework questions."
                elif has_study_tasks:
                    goal += "\n\nFor the study topics, I'll walk you through the material conversationally so you really understand it."

                if assignment_steps:
                    preview_steps = assignment_steps[:5]
                    goal += "\n\nFor assignment work, focus checklist items now:\n" + "\n".join(
                        [f"- {item}" for item in preview_steps]
                    )
                    if len(assignment_steps) > len(preview_steps):
                        goal += f"\n- (+{len(assignment_steps) - len(preview_steps)} more checklist item(s))"
                
                # Use the start time of the first due slot
                scheduled_for = due_slots[0].start_at.isoformat()

            logger.info(
                "Calling user about %d soft event slot(s) due around %s",
                len(due_slots),
                due_slots[0].start_at.isoformat(),
            )

            # Make a single call for all due slots.
            session = create_session(goal=goal, scheduled_for=scheduled_for)
            if session:
                session_id = session.get("id") if isinstance(session, dict) else session.id
                call_time = timezone.now()
                
                # Mark all slots as called in a batch.
                for slot in due_slots:
                    slot.call_made_at = call_time
                    slot.metadata = slot.metadata or {}
                    slot.metadata["call_session_id"] = str(session_id)
                    slot.save(update_fields=["call_made_at", "metadata", "updated_at"])
                
                logger.info(
                    "Called user for %d slot(s) (session: %s)",
                    len(due_slots),
                    session_id,
                )
        except Exception as exc:
            logger.exception("Failed to make call for soft event slots: %s", exc)
