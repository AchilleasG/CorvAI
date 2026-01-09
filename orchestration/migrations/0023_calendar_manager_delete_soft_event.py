from django.db import migrations


def seed_delete_soft_event(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    try:
        module = ToolModule.objects.get(slug="calendar_manager")
    except ToolModule.DoesNotExist:
        return

    ToolFunction.objects.update_or_create(
        manifest_id="calendar_manager.delete_soft_event",
        defaults={
            "module": module,
            "name": "calendar_manager.delete_soft_event",
            "description": "Delete (archive) a soft event and cancel its planned slots.",
            "params_schema": {
                "type": "object",
                "properties": {"soft_event_id": {"type": "string"}},
                "required": ["soft_event_id"],
            },
            "return_schema": {
                "type": "object",
                "properties": {"deleted": {"type": "integer"}, "canceled_slots": {"type": "integer"}},
            },
            "deprecated": False,
            "handler_ref": "orchestration.tools.calendar_manager.delete_soft_event",
        },
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0022_remove_calendar_module"),
    ]

    operations = [
        migrations.RunPython(seed_delete_soft_event, noop),
    ]
