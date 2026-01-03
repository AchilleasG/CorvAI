from django.db import migrations
import json


def update_params(apps, schema_editor):
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    try:
        tf = ToolFunction.objects.get(manifest_id="soft_events.list_soft_events")
    except ToolFunction.DoesNotExist:
        return
    tf.params_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by event status (active/paused/archived)"},
            "slot_status": {"type": "string", "description": "Optional slot status filter (planned, completed, etc.)"},
        },
    }
    tf.return_schema = {
        "type": "object",
        "properties": {
            "events": {"type": "array", "items": {"type": "object"}},
        },
    }
    tf.save(update_fields=["params_schema", "return_schema"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0014_soft_events_functions"),
    ]

    operations = [
        migrations.RunPython(update_params, noop),
    ]
