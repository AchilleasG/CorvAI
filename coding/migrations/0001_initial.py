# Generated manually for the Corv coding-session module.
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("ssh_connections", "0002_persistent_shell_tools")]
    operations = [
        migrations.CreateModel(
            name="CodingSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=160)),
                ("remote_working_directory", models.CharField(default="~", max_length=1024)),
                ("status", models.CharField(choices=[("ready", "Ready"), ("running", "Running"), ("needs_input", "Needs input"), ("direct", "Direct CLI"), ("failed", "Failed"), ("stopped", "Stopped")], default="ready", max_length=24)),
                ("permission_mode", models.CharField(default="danger-full-access", max_length=32)),
                ("codex_thread_id", models.CharField(blank=True, default="", max_length=128)),
                ("tmux_session_name", models.CharField(blank=True, default="", max_length=128)),
                ("last_summary", models.TextField(blank=True, default="")),
                ("pending_question", models.TextField(blank=True, default="")),
                ("pending_options", models.JSONField(blank=True, default=list)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("stopped_at", models.DateTimeField(blank=True, null=True)),
                ("machine", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="coding_sessions", to="ssh_connections.sshmachine")),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.CreateModel(
            name="CodingTurn",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source", models.CharField(choices=[("corv", "Corv"), ("ui", "Coding module"), ("decision", "Decision")], default="ui", max_length=24)),
                ("prompt", models.TextField()),
                ("status", models.CharField(choices=[("queued", "Queued"), ("running", "Running"), ("completed", "Completed"), ("needs_input", "Needs input"), ("failed", "Failed"), ("cancelled", "Cancelled")], default="queued", max_length=24)),
                ("codex_thread_id", models.CharField(blank=True, default="", max_length=128)),
                ("summary", models.TextField(blank=True, default="")),
                ("question", models.TextField(blank=True, default="")),
                ("options", models.JSONField(blank=True, default=list)),
                ("event_log", models.TextField(blank=True, default="")),
                ("error", models.TextField(blank=True, default="")),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="turns", to="coding.codingsession")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="codingsession", index=models.Index(fields=["status", "updated_at"], name="coding_codi_status_669a38_idx")),
        migrations.AddIndex(model_name="codingturn", index=models.Index(fields=["session", "created_at"], name="coding_codi_session_c771b2_idx")),
    ]
