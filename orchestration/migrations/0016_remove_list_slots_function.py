from django.db import migrations


def remove_list_slots(apps, schema_editor):
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    ToolFunction.objects.filter(manifest_id="soft_events.list_slots").delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0015_update_soft_events_functions"),
    ]

    operations = [
        migrations.RunPython(remove_list_slots, noop),
    ]
