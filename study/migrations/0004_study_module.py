from django.db import migrations


def seed_study_module(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module, _ = ToolModule.objects.update_or_create(
        slug="study",
        defaults={
            "name": "Study",
            "description": (
                "Manage courses, exams, topics, materials, study plans, and session targets. "
                "Ingest uploaded materials by converting page images directly into markdown and solved notes. "
                "Keep one active plan per course and use variable-duration study sessions."
            ),
            "caller_instructions": (
                "Use study.* for course setup, material ingestion, and study planning. "
                "First ingest materials, then extract topics and theory, then create or refresh the active plan. "
                "Keep one active plan per course. "
                "For sessions, prefer variable durations using study session targets and soft events. "
                "When a material contains diagrams, equations, or handwritten content, rely on image understanding rather than external OCR."
            ),
        },
    )

    functions = {
        "study.create_course": {
            "description": "Create a study course container for one subject or class.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "code": {"type": "string"},
                    "description": {"type": "string"},
                    "term_start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "term_end_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "status": {"type": "string", "description": "active|completed|archived"},
                    "chat_id": {"type": "string"},
                },
                "required": ["title"],
            },
        },
        "study.list_courses": {
            "description": "List study courses.",
            "params_schema": {"type": "object", "properties": {"status": {"type": "string"}}},
        },
        "study.create_exam": {
            "description": "Create an exam checkpoint for a study course.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "title": {"type": "string"},
                    "kind": {"type": "string"},
                    "scheduled_at": {"type": "string", "description": "ISO datetime"},
                    "weight": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": ["course_id", "title"],
            },
        },
        "study.create_topic": {
            "description": "Create a topic for a course.",
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
        "study.ingest_directory": {
            "description": "Ingest a directory of study materials and convert them to markdown and theory notes.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "directory": {"type": "string"},
                    "recursive": {"type": "boolean", "default": True},
                    "max_pages": {"type": "integer"},
                },
                "required": ["course_id", "directory"],
            },
        },
        "study.process_material": {
            "description": "Process one study material into markdown, solved work, and extracted theory.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "material_id": {"type": "string"},
                    "max_pages": {"type": "integer"},
                },
                "required": ["material_id"],
            },
        },
        "study.create_active_plan": {
            "description": "Create a new active study plan for a course and supersede the old one.",
            "params_schema": {
                "type": "object",
                "properties": {"course_id": {"type": "string"}, "name": {"type": "string"}},
                "required": ["course_id"],
            },
        },
        "study.build_session_targets": {
            "description": "Build study session targets from the active plan and topic list.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "preferred_minutes": {"type": "integer", "default": 60},
                    "min_minutes": {"type": "integer", "default": 30},
                },
                "required": ["plan_id", "start_date", "end_date"],
            },
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
        ("study", "0003_studymaterial_converted_markdown_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_study_module, noop),
    ]
