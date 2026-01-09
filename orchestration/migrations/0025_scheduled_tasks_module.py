from django.db import migrations
import json


def seed_scheduled_tasks(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module, _ = ToolModule.objects.update_or_create(
        slug="scheduled_tasks",
        defaults={
            "name": "Scheduled Tasks",
            "description": "Create and manage scheduled tasks that run later without chat context.",
            "caller_instructions": (
                "Scheduled tasks run without user clarification. "
                "Assume missing details and proceed with best effort. "
                "Use scheduled_tasks.* to create/update/list/delete tasks and view logs."
            ),
        },
    )

    functions = {
        "scheduled_tasks.create_task": {
            "description": "Create a scheduled task that runs later via the Function Caller.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "start_at": {"type": "string", "description": "ISO datetime when the task should first run"},
                    "recurrence": {"type": "string", "description": "once|daily|weekly|monthly"},
                },
                "required": ["prompt"],
            },
            "return_schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "status": {"type": "string"},
                    "next_run_at": {"type": "string"},
                },
            },
        },
        "scheduled_tasks.list_tasks": {
            "description": "List scheduled tasks with optional status filter.",
            "params_schema": {
                "type": "object",
                "properties": {"status": {"type": "string", "description": "active|paused|completed"}},
            },
            "return_schema": {"type": "object"},
        },
        "scheduled_tasks.update_task": {
            "description": "Update a scheduled task (prompt/start/recur/status).",
            "params_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "start_at": {"type": "string", "description": "ISO datetime"},
                    "recurrence": {"type": "string", "description": "once|daily|weekly|monthly"},
                    "status": {"type": "string", "description": "active|paused|completed"},
                },
                "required": ["task_id"],
            },
            "return_schema": {"type": "object"},
        },
        "scheduled_tasks.delete_task": {
            "description": "Delete a scheduled task and its history.",
            "params_schema": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
            "return_schema": {"type": "object"},
        },
        "scheduled_tasks.list_runs": {
            "description": "List recent runs and logs for a scheduled task.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["task_id"],
            },
            "return_schema": {"type": "object"},
        },
    }
    for manifest_id, payload in functions.items():
        handler_ref = manifest_id.replace("scheduled_tasks.", "orchestration.tools.scheduled_tasks.")
        ToolFunction.objects.update_or_create(
            manifest_id=manifest_id,
            defaults={
                "module": module,
                "name": manifest_id,
                "description": payload["description"],
                "params_schema": payload["params_schema"],
                "return_schema": payload["return_schema"],
                "deprecated": False,
                "handler_ref": handler_ref,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0024_scheduled_tasks"),
    ]

    operations = [
        migrations.RunPython(seed_scheduled_tasks, noop),
    ]
