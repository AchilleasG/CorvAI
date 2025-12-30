from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0002_frontmanpersona"),
    ]

    operations = [
        migrations.AddField(
            model_name="toolmodule",
            name="caller_instructions",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Hints for the Function Caller when planning tool use.",
            ),
        ),
    ]
