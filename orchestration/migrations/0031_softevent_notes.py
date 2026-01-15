from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0030_calendar_manager_habits"),
    ]

    operations = [
        migrations.AddField(
            model_name="softevent",
            name="notes",
            field=models.TextField(blank=True, default=""),
        ),
    ]
