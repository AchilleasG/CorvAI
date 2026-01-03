from django.db import migrations


def remove_soft_events(apps, schema_editor):
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction.objects.filter(module__slug="soft_events").delete()
    ToolModule.objects.filter(slug="soft_events").delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0018_calendar_manager_module"),
    ]

    operations = [
        migrations.RunPython(remove_soft_events, noop),
    ]
