from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0034_update_soft_event_params"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="softevent",
            name="duration_minutes",
        ),
        migrations.AddField(
            model_name="softevent",
            name="preferred_duration_minutes",
            field=models.PositiveIntegerField(
                default=60,
                help_text="Preferred session duration in minutes.",
            ),
        ),
        migrations.AddField(
            model_name="softevent",
            name="min_duration_minutes",
            field=models.PositiveIntegerField(
                default=30,
                help_text="Minimum acceptable duration; scheduler will pack shorter slots if needed.",
            ),
        ),
    ]
