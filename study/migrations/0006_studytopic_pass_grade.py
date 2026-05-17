from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("study", "0005_study_tool_expansion"),
    ]

    operations = [
        migrations.AddField(
            model_name="studytopic",
            name="passed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="studytopic",
            name="passed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="studytopic",
            name="grade",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
