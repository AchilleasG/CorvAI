from django.db import migrations


def seed_study_tool_updates(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module = ToolModule.objects.filter(slug="study").first()
    if not module:
        return

    module.caller_instructions = (
        "Use study.* for course setup, lesson/topic management, material tracking, exam checkpoints, ingestion, and study planning. "
        "First ingest materials, then extract topics and theory, then create or refresh the active plan. "
        "Keep one active plan per course. "
        "For sessions, prefer variable durations using study session targets and soft events. "
        "When a material contains diagrams, equations, or handwritten content, rely on image understanding rather than external OCR. "
        "Use study.create_lesson and study.list_lessons as human-friendly aliases for topic management. "
        "Use study.create_material and study.list_materials to track study files, links, and notes. "
        "Use study.update_topic to mark a lesson passed and assign a grade when the user finishes it."
    )
    module.save(update_fields=["caller_instructions"])

    payload = {
        "description": "Update a topic or lesson, including pass state and grade.",
        "params_schema": {
            "type": "object",
            "properties": {
                "topic_id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "order_index": {"type": "integer"},
                "estimated_effort_minutes": {"type": "integer"},
                "weight": {"type": "number"},
                "status": {"type": "string"},
                "passed": {"type": "boolean"},
                "grade": {"type": "number"},
            },
            "required": ["topic_id"],
        },
    }

    ToolFunction.objects.update_or_create(
        manifest_id="study.update_topic",
        defaults={
            "module": module,
            "name": "study.update_topic",
            "description": payload["description"],
            "params_schema": payload["params_schema"],
            "return_schema": {"type": "object"},
            "deprecated": False,
            "handler_ref": "study.tools.update_topic",
        },
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("study", "0006_studytopic_pass_grade"),
    ]

    operations = [
        migrations.RunPython(seed_study_tool_updates, noop),
    ]
