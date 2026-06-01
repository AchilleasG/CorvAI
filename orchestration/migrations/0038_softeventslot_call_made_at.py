from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0037_update_calendar_manager_variable_duration_instructions"),
    ]

    operations = [
        migrations.AddField(
            model_name="softeventslot",
            name="call_made_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="When a call notification was made about this slot.",
            ),
        ),
        migrations.AddIndex(
            model_name="softeventslot",
            index=models.Index(fields=["call_made_at"], name="orchestration_softeventslot_call_made_at_idx"),
        ),
    ]
