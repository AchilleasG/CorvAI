from django.db import migrations


def seed_update_delete(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    try:
        module = ToolModule.objects.get(slug="calendar_manager")
    except ToolModule.DoesNotExist:
        return

    for manifest_id, desc, handler in [
        ("calendar_manager.update_event", "Update a hard calendar event (Google Calendar).", "orchestration.tools.calendar_manager.update_event"),
        ("calendar_manager.delete_event", "Delete a hard calendar event (Google Calendar).", "orchestration.tools.calendar_manager.delete_event"),
    ]:
        ToolFunction.objects.update_or_create(
            manifest_id=manifest_id,
            defaults={
                "module": module,
                "name": manifest_id,
                "description": desc,
                "params_schema": {},
                "return_schema": {},
                "deprecated": False,
                "handler_ref": handler,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0020_deprecate_calendar_module"),
    ]

    operations = [
        migrations.RunPython(seed_update_delete, noop),
    ]
