from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0032_calendar_manager_soft_event_notes_tools"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="softevent",
            name="preferred_dayparts",
        ),
    ]
