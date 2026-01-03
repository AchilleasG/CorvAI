from django.db import migrations


def deprecate_calendar(apps, schema_editor):
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    ToolModule = apps.get_model("orchestration", "ToolModule")

    # Mark calendar functions deprecated and clear caller instructions so LLM favors calendar_manager.
    ToolFunction.objects.filter(module__slug="calendar").update(deprecated=True)
    ToolModule.objects.filter(slug="calendar").update(caller_instructions="Deprecated; use calendar_manager.* instead.")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0019_remove_soft_events_module"),
    ]

    operations = [
        migrations.RunPython(deprecate_calendar, noop),
    ]
