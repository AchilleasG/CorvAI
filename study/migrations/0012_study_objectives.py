from datetime import datetime, time

from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def _make_aware(dt):
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def backfill_study_objectives(apps, schema_editor):
    Objective = apps.get_model("orchestration", "Objective")
    ObjectiveTask = apps.get_model("orchestration", "ObjectiveTask")
    SoftEvent = apps.get_model("orchestration", "SoftEvent")
    SoftEventObjective = apps.get_model("orchestration", "SoftEventObjective")
    StudyCourse = apps.get_model("study", "StudyCourse")
    StudyTopic = apps.get_model("study", "StudyTopic")
    StudyAssignment = apps.get_model("study", "StudyAssignment")

    course_objectives: dict[str, str] = {}

    for course in StudyCourse.objects.all().order_by("created_at"):
        deadline_at = None
        exam = course.exams.exclude(scheduled_at__isnull=True).order_by("scheduled_at").first()
        if exam and exam.scheduled_at:
            deadline_at = exam.scheduled_at
        elif course.term_end_date:
            deadline_at = _make_aware(datetime.combine(course.term_end_date, time(hour=23, minute=59)))
        objective = Objective.objects.create(
            title=course.code or course.title,
            description=course.description or "",
            deadline_at=deadline_at,
            notes=f"Study course objective for {course.title}",
            metadata={"source": "study_course", "study_course_id": str(course.id)},
            chat_id=course.chat_id,
        )
        course.objective_id = objective.id
        course.save(update_fields=["objective"])
        course_objectives[str(course.id)] = str(objective.id)

    for topic in StudyTopic.objects.select_related("course").all().order_by("course_id", "order_index", "created_at"):
        parent_id = course_objectives[str(topic.course_id)]
        estimated = max(int(topic.estimated_effort_minutes or 60), 1)
        objective = Objective.objects.create(
            parent_id=parent_id,
            title=f"Study {topic.name}",
            description=topic.summary or topic.description or "",
            deadline_at=Objective.objects.get(id=parent_id).deadline_at,
            estimated_effort_minutes=estimated,
            remaining_effort_minutes=estimated,
            priority=int(round(float(topic.weight or 1.0) * 10)),
            metadata={
                "source": "study_topic",
                "study_course_id": str(topic.course_id),
                "study_topic_id": str(topic.id),
                "topic_status": topic.status,
            },
            chat_id=topic.course.chat_id,
        )
        topic.objective_id = objective.id
        topic.save(update_fields=["objective"])
        homework_items = topic.homework if isinstance(topic.homework, list) else []
        for idx, item in enumerate(homework_items, start=1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("question") or "").strip()
            if not text:
                continue
            label = str(item.get("source_exercise_label") or "").strip() or f"Homework item {idx}"
            done = bool(item.get("done"))
            ObjectiveTask.objects.create(
                objective_id=objective.id,
                title=label[:255],
                description=text,
                status="done" if done else "todo",
                sort_order=idx,
                due_at=objective.deadline_at,
                completed_at=timezone.now() if done else None,
                metadata={
                    "external_key": f"topic-homework:{str(item.get('assignment_id') or f'{topic.id}:{idx}')}",
                    "source": "study_topic_homework",
                    "assignment_id": str(item.get("assignment_id") or f"{topic.id}:{idx}"),
                    "source_material_id": item.get("source_material_id"),
                    "source_material_title": item.get("source_material_title"),
                    "question_index": item.get("question_index"),
                },
            )

    for assignment in StudyAssignment.objects.select_related("course").all().order_by("created_at"):
        parent_id = course_objectives[str(assignment.course_id)]
        estimated = max(int(assignment.session_count or 1) * 120, 30)
        objective = Objective.objects.create(
            parent_id=parent_id,
            title=f"Complete {assignment.title}",
            description=assignment.plan or assignment.description or "",
            deadline_at=assignment.due_at,
            estimated_effort_minutes=estimated,
            remaining_effort_minutes=estimated,
            priority=8,
            metadata={
                "source": "study_assignment",
                "study_course_id": str(assignment.course_id),
                "study_assignment_id": str(assignment.id),
                "assignment_status": assignment.status,
            },
            chat_id=assignment.course.chat_id,
        )
        assignment.objective_id = objective.id
        assignment.save(update_fields=["objective"])
        checklist = assignment.checklist if isinstance(assignment.checklist, list) else []
        estimated_each = max(int(estimated / max(len(checklist), 1)), 30) if checklist else None
        for idx, item in enumerate(checklist, start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip() or f"Assignment step {idx}"
            description = str(item.get("description") or "").strip()
            ObjectiveTask.objects.create(
                objective_id=objective.id,
                title=title[:255],
                description=description,
                status="todo",
                sort_order=int(item.get("step_number") or idx),
                due_at=assignment.due_at,
                estimated_effort_minutes=estimated_each,
                remaining_effort_minutes=estimated_each,
                metadata={
                    "external_key": f"assignment-checklist:{idx}",
                    "source": "study_assignment_checklist",
                    "step_number": int(item.get("step_number") or idx),
                },
            )
        for raw_soft_event_id in assignment.soft_event_refs or []:
            text = str(raw_soft_event_id or "").strip()
            if not text:
                continue
            soft_event = SoftEvent.objects.filter(id=text).first()
            if soft_event is None:
                continue
            SoftEventObjective.objects.get_or_create(
                soft_event_id=soft_event.id,
                objective_id=objective.id,
                defaults={"role": "primary"},
            )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("orchestration", "0040_objectives"),
        ("study", "0011_studyassignment"),
    ]

    operations = [
        migrations.AddField(
            model_name="studycourse",
            name="objective",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="study_course", to="orchestration.objective"),
        ),
        migrations.AddField(
            model_name="studytopic",
            name="objective",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="study_topic", to="orchestration.objective"),
        ),
        migrations.AddField(
            model_name="studyassignment",
            name="objective",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="study_assignment", to="orchestration.objective"),
        ),
        migrations.RunPython(backfill_study_objectives, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="studycourse",
            name="objective",
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="study_course", to="orchestration.objective"),
        ),
        migrations.AlterField(
            model_name="studytopic",
            name="objective",
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="study_topic", to="orchestration.objective"),
        ),
        migrations.AlterField(
            model_name="studyassignment",
            name="objective",
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="study_assignment", to="orchestration.objective"),
        ),
    ]
