import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("coding", "0006_flexible_conversation_watches")]

    operations = [
        migrations.CreateModel(
            name="CodexRuntimeUpdate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed")], default="queued", max_length=16)),
                ("previous_version", models.CharField(blank=True, default="", max_length=64)),
                ("version", models.CharField(blank=True, default="", max_length=64)),
                ("log", models.TextField(blank=True, default="")),
                ("error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-created_at"]},
        )
    ]
