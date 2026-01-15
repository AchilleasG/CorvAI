from django.db import migrations


def update_soft_event_params(apps, schema_editor):
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    create_params = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "notes": {"type": "string", "description": "Optional scheduling notes"},
            "duration_minutes": {"type": "integer", "default": 30},
            "soft_deadline": {"type": "string", "description": "ISO datetime deadline (soft)"},
            "hard_deadline": {"type": "string", "description": "ISO datetime deadline (hard)"},
            "frequency": {"type": "string", "description": "Optional recurrence description (e.g., weekly)"},
            "deferral_limit": {"type": "integer", "default": 3},
            "priority": {"type": "integer", "default": 0, "description": "Higher = more urgent"},
            "chat_id": {"type": "string", "description": "Optional chat id for context/notifications"},
        },
        "required": ["title"],
    }

    ToolFunction.objects.filter(
        manifest_id__in=["calendar_manager.create_soft_event", "soft_events.create_soft_event"]
    ).update(params_schema=create_params)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0033_remove_preferred_dayparts"),
    ]

    operations = [
        migrations.RunPython(update_soft_event_params, noop),
    ]
