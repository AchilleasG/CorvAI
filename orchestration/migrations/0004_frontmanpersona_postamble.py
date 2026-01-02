from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0003_toolmodule_caller_instructions"),
    ]

    operations = [
        migrations.AddField(
            model_name="frontmanpersona",
            name="postamble",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Optional instructions appended after persona to further steer Front Man.",
            ),
        ),
    ]
