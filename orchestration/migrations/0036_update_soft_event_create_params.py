from django.db import migrations


def update_soft_event_create_params(apps, schema_editor):
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    create_params = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "notes": {"type": "string", "description": "Optional scheduling notes"},
            "preferred_duration_minutes": {"type": "integer", "default": 60, "description": "Preferred duration in minutes"},
            "min_duration_minutes": {"type": "integer", "default": 30, "description": "Minimum acceptable duration"},
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
        ("orchestration", "0035_softevent_variable_duration"),
    ]

    operations = [
        migrations.RunPython(update_soft_event_create_params, noop),
    ]
