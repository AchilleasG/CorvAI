from django.db import migrations


def seed_objectives_module(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module, _ = ToolModule.objects.get_or_create(
        slug="objectives",
        defaults={
            "name": "Objectives",
            "description": "Manage hierarchical objectives, tasks, and progress logs.",
            "tags": ["planning", "objectives", "tasks"],
        },
    )
    if not module.name:
        module.name = "Objectives"
    if not module.description:
        module.description = "Manage hierarchical objectives, tasks, and progress logs."
    module.save(update_fields=["name", "description", "updated_at"])

    functions = {
        "objectives.list_objectives": {
            "description": "List root objectives or children under a parent.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "parent_id": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
        },
        "objectives.get_objective": {
            "description": "Get an objective with tasks and recent logs.",
            "params_schema": {
                "type": "object",
                "properties": {"objective_id": {"type": "string"}},
                "required": ["objective_id"],
            },
        },
        "objectives.create_objective": {
            "description": "Create a new objective.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "parent_id": {"type": "string"},
                    "description": {"type": "string"},
                    "deadline_at": {"type": "string"},
                    "estimated_effort_minutes": {"type": "integer"},
                    "remaining_effort_minutes": {"type": "integer"},
                    "priority": {"type": "integer"},
                    "notes": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["title"],
            },
        },
        "objectives.update_objective": {
            "description": "Update an objective.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "objective_id": {"type": "string"},
                    "parent_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string"},
                    "deadline_at": {"type": "string"},
                    "estimated_effort_minutes": {"type": "integer"},
                    "remaining_effort_minutes": {"type": "integer"},
                    "priority": {"type": "integer"},
                    "notes": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["objective_id"],
            },
        },
        "objectives.delete_objective": {
            "description": "Delete an objective.",
            "params_schema": {
                "type": "object",
                "properties": {"objective_id": {"type": "string"}},
                "required": ["objective_id"],
            },
        },
        "objectives.create_task": {
            "description": "Create a task under an objective.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "objective_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string"},
                    "estimated_effort_minutes": {"type": "integer"},
                    "remaining_effort_minutes": {"type": "integer"},
                    "due_at": {"type": "string"},
                    "sort_order": {"type": "integer"},
                    "metadata": {"type": "object"},
                },
                "required": ["objective_id", "title"],
            },
        },
        "objectives.update_task": {
            "description": "Update an objective task.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string"},
                    "estimated_effort_minutes": {"type": "integer"},
                    "remaining_effort_minutes": {"type": "integer"},
                    "due_at": {"type": "string"},
                    "sort_order": {"type": "integer"},
                    "metadata": {"type": "object"},
                },
                "required": ["task_id"],
            },
        },
        "objectives.delete_task": {
            "description": "Delete an objective task.",
            "params_schema": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        },
        "objectives.list_logs": {
            "description": "List logs for an objective.",
            "params_schema": {
                "type": "object",
                "properties": {"objective_id": {"type": "string"}},
                "required": ["objective_id"],
            },
        },
        "objectives.create_log": {
            "description": "Create a log entry for an objective or task.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "objective_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "text": {"type": "string"},
                    "minutes_spent": {"type": "integer"},
                    "logged_at": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["objective_id"],
            },
        },
        "objectives.update_log": {
            "description": "Update an objective log entry.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "log_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "text": {"type": "string"},
                    "minutes_spent": {"type": "integer"},
                    "logged_at": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["log_id"],
            },
        },
        "objectives.delete_log": {
            "description": "Delete an objective log entry.",
            "params_schema": {
                "type": "object",
                "properties": {"log_id": {"type": "string"}},
                "required": ["log_id"],
            },
        },
    }

    for manifest_id, payload in functions.items():
        handler_ref = manifest_id.replace("objectives.", "orchestration.tools.objectives.")
        ToolFunction.objects.update_or_create(
            manifest_id=manifest_id,
            defaults={
                "module": module,
                "name": manifest_id,
                "description": payload["description"],
                "params_schema": payload["params_schema"],
                "return_schema": {"type": "object"},
                "deprecated": False,
                "handler_ref": handler_ref,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0040_objectives"),
    ]

    operations = [
        migrations.RunPython(seed_objectives_module, noop),
    ]
