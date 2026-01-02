from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0005_frontmanpersona_is_active"),
    ]

    operations = [
        migrations.AddField(
            model_name="toolmodule",
            name="secrets_encrypted",
            field=models.TextField(blank=True, default="", help_text="Encrypted secrets blob"),
        ),
    ]
