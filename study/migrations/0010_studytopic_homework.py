from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("study", "0009_studytopic_summary"),
    ]

    operations = [
        migrations.AddField(
            model_name="studytopic",
            name="homework",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Assigned past-exam homework questions for this lesson",
            ),
        ),
    ]
