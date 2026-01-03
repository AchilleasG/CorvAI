from django.db import migrations


def remove_calendar(apps, schema_editor):
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction.objects.filter(module__slug="calendar").delete()
    ToolModule.objects.filter(slug="calendar").delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0021_calendar_manager_update_delete"),
    ]

    operations = [
        migrations.RunPython(remove_calendar, noop),
    ]
