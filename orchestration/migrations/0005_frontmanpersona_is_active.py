from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0004_frontmanpersona_postamble"),
    ]

    operations = [
        migrations.AddField(
            model_name="frontmanpersona",
            name="is_active",
            field=models.BooleanField(
                default=False,
                help_text="If true, this persona is the active one used by Frontman.",
            ),
        ),
    ]
