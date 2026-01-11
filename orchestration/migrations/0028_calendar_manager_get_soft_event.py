from django.db import migrations


def seed_get_soft_event(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    try:
        module = ToolModule.objects.get(slug="calendar_manager")
    except ToolModule.DoesNotExist:
        return

    ToolFunction.objects.update_or_create(
        manifest_id="calendar_manager.get_soft_event",
        defaults={
            "module": module,
            "name": "calendar_manager.get_soft_event",
            "description": "Get a soft event by id with its slots.",
            "params_schema": {},
            "return_schema": {},
            "deprecated": False,
            "handler_ref": "orchestration.tools.calendar_manager.get_soft_event",
        },
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0027_call_sessions_module"),
    ]

    operations = [
        migrations.RunPython(seed_get_soft_event, noop),
    ]
