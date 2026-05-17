from django.db import migrations


def seed_study_tool_expansion(apps, schema_editor):
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
        "Use study.create_material and study.list_materials to track study files, links, and notes."
    )
    module.save(update_fields=["caller_instructions"])

    functions = {
        "study.create_lesson": {
            "description": "Create a lesson entry for a course. This is an alias for creating a topic.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "order_index": {"type": "integer"},
                    "estimated_effort_minutes": {"type": "integer"},
                    "weight": {"type": "number"},
                },
                "required": ["course_id", "name"],
            },
        },
        "study.list_topics": {
            "description": "List topics for a study course.",
            "params_schema": {"type": "object", "properties": {"course_id": {"type": "string"}}, "required": ["course_id"]},
        },
        "study.list_lessons": {
            "description": "List lessons for a study course. This is an alias for listing topics.",
            "params_schema": {"type": "object", "properties": {"course_id": {"type": "string"}}, "required": ["course_id"]},
        },
        "study.create_material": {
            "description": "Create a study material record for a course.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "title": {"type": "string"},
                    "kind": {"type": "string"},
                    "topic_id": {"type": "string"},
                    "exam_id": {"type": "string"},
                    "source_url": {"type": "string"},
                    "file_path": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["course_id", "title"],
            },
        },
        "study.list_materials": {
            "description": "List study materials for a course.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["course_id"],
            },
        },
        "study.list_exams": {
            "description": "List exams for a study course.",
            "params_schema": {"type": "object", "properties": {"course_id": {"type": "string"}}, "required": ["course_id"]},
        },
    }

    for manifest_id, payload in functions.items():
        ToolFunction.objects.update_or_create(
            manifest_id=manifest_id,
            defaults={
                "module": module,
                "name": manifest_id,
                "description": payload["description"],
                "params_schema": payload["params_schema"],
                "return_schema": {"type": "object"},
                "deprecated": False,
                "handler_ref": f"study.tools.{manifest_id.split('.', 1)[1]}",
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("study", "0004_study_module"),
    ]

    operations = [
        migrations.RunPython(seed_study_tool_expansion, noop),
    ]
