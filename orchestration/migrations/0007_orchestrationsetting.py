from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0006_toolmodule_secrets_encrypted"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrchestrationSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=255, unique=True)),
                ("value", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["key"],
            },
        ),
        migrations.AddIndex(
            model_name="orchestrationsetting",
            index=models.Index(fields=["key"], name="orchestrati_key_5f2c2b_idx"),
        ),
    ]
