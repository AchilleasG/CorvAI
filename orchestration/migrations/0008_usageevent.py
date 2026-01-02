from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0007_orchestrationsetting"),
    ]

    operations = [
        migrations.CreateModel(
            name="UsageEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("frontman_decision", "Frontman Decision"),
                            ("frontman_generate", "Frontman Generate"),
                            ("caller_plan", "Caller Plan"),
                        ],
                        max_length=64,
                    ),
                ),
                ("model", models.CharField(blank=True, default="", max_length=128)),
                ("cache_mode", models.CharField(blank=True, default="", max_length=32)),
                ("prompt_tokens", models.IntegerField(default=0)),
                ("cached_prompt_tokens", models.IntegerField(default=0)),
                ("completion_tokens", models.IntegerField(default=0)),
                ("total_tokens", models.IntegerField(default=0)),
                ("prompt_cache_key", models.CharField(blank=True, default="", max_length=255)),
                (
                    "job",
                    models.ForeignKey(
                        null=True,
                        blank=True,
                        on_delete=models.SET_NULL,
                        related_name="usage_events",
                        to="orchestration.job",
                    ),
                ),
                (
                    "chat",
                    models.ForeignKey(
                        null=True,
                        blank=True,
                        on_delete=models.SET_NULL,
                        related_name="usage_events",
                        to="chat.chat",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="usageevent",
            index=models.Index(fields=["created_at"], name="orchestrati_created_f4c7bf_idx"),
        ),
        migrations.AddIndex(
            model_name="usageevent",
            index=models.Index(fields=["source"], name="orchestrati_source_d9b56a_idx"),
        ),
        migrations.AddIndex(
            model_name="usageevent",
            index=models.Index(fields=["model"], name="orchestrati_model_34cf3a_idx"),
        ),
    ]
