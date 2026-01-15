from django.db import migrations


def add_soft_event_notes_tools(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module, _ = ToolModule.objects.get_or_create(slug="calendar_manager")
    if module.caller_instructions:
        extra = "Soft events may include notes; treat them as scheduling constraints and context."
        if extra not in module.caller_instructions:
            module.caller_instructions = f"{module.caller_instructions}\n{extra}".strip()
            module.save(update_fields=["caller_instructions"])

    ToolFunction.objects.update_or_create(
        manifest_id="calendar_manager.create_soft_event",
        defaults={
            "module": module,
            "name": "calendar_manager.create_soft_event",
            "description": "Create a flexible soft event (task) that can be scheduled by Corv.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "notes": {"type": "string", "description": "Optional scheduling notes"},
                    "duration_minutes": {"type": "integer", "default": 30},
                    "soft_deadline": {"type": "string", "description": "ISO datetime deadline (soft)"},
                    "hard_deadline": {"type": "string", "description": "ISO datetime deadline (hard)"},
                    "frequency": {
                        "type": "string",
                        "description": "Optional recurrence description (e.g., weekly)",
                    },
                    "preferred_dayparts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Hints like morning/afternoon/evening",
                    },
                    "deferral_limit": {"type": "integer", "default": 3},
                    "priority": {"type": "integer", "default": 0, "description": "Higher = more urgent"},
                    "chat_id": {"type": "string", "description": "Optional chat id for context/notifications"},
                },
                "required": ["title"],
            },
            "return_schema": {"type": "object"},
            "deprecated": False,
            "handler_ref": "orchestration.tools.calendar_manager.create_soft_event",
        },
    )

    functions = {
        "calendar_manager.get_soft_event_notes": {
            "description": "Get notes for a soft event.",
            "params_schema": {
                "type": "object",
                "properties": {"soft_event_id": {"type": "string"}},
                "required": ["soft_event_id"],
            },
        },
        "calendar_manager.set_soft_event_notes": {
            "description": "Overwrite notes for a soft event.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "soft_event_id": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["soft_event_id", "notes"],
            },
        },
        "calendar_manager.append_soft_event_notes": {
            "description": "Append notes for a soft event.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "soft_event_id": {"type": "string"},
                    "notes": {"type": "string"},
                    "separator": {"type": "string", "default": "\n"},
                },
                "required": ["soft_event_id", "notes"],
            },
        },
        "calendar_manager.clear_soft_event_notes": {
            "description": "Clear notes for a soft event.",
            "params_schema": {
                "type": "object",
                "properties": {"soft_event_id": {"type": "string"}},
                "required": ["soft_event_id"],
            },
        },
        "calendar_manager.delete_soft_event_notes": {
            "description": "Delete notes for a soft event (alias of clear).",
            "params_schema": {
                "type": "object",
                "properties": {"soft_event_id": {"type": "string"}},
                "required": ["soft_event_id"],
            },
        },
    }

    for manifest_id, payload in functions.items():
        handler_ref = manifest_id.replace(
            "calendar_manager.", "orchestration.tools.calendar_manager."
        )
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
        ("orchestration", "0031_softevent_notes"),
    ]

    operations = [
        migrations.RunPython(add_soft_event_notes_tools, noop),
    ]
