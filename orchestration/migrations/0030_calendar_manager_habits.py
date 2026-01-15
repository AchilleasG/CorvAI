from django.db import migrations


def add_calendar_manager_habits(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module, _ = ToolModule.objects.get_or_create(slug="calendar_manager")

    functions = {
        "calendar_manager.get_habits": {
            "description": "Get scheduling habits and routine notes.",
            "params_schema": {"type": "object", "properties": {}},
        },
        "calendar_manager.set_habits": {
            "description": "Overwrite scheduling habits and routine notes.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Full habits text to store"},
                },
                "required": ["text"],
            },
        },
        "calendar_manager.append_habits": {
            "description": "Append text to scheduling habits and routine notes.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to append"},
                    "separator": {"type": "string", "description": "Separator between entries", "default": "\n"},
                },
                "required": ["text"],
            },
        },
        "calendar_manager.clear_habits": {
            "description": "Clear scheduling habits and routine notes.",
            "params_schema": {"type": "object", "properties": {}},
        },
        "calendar_manager.delete_habits": {
            "description": "Delete scheduling habits and routine notes (alias of clear).",
            "params_schema": {"type": "object", "properties": {}},
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
        ("orchestration", "0029_merge_20260115_1629"),
    ]

    operations = [
        migrations.RunPython(add_calendar_manager_habits, noop),
    ]
