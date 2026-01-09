from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0025_scheduled_tasks_module"),
    ]

    operations = [
        migrations.CreateModel(
            name="PushToken",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("token", models.TextField(unique=True)),
                ("platform", models.CharField(choices=[("ios", "iOS"), ("android", "Android"), ("web", "Web"), ("unknown", "Unknown")], default="unknown", max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-last_seen_at"],
            },
        ),
        migrations.CreateModel(
            name="UserMessage",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("title", models.TextField(blank=True, default="")),
                ("body", models.TextField(blank=True, default="")),
                ("kind", models.CharField(choices=[("info", "Info"), ("call_missed", "Call missed"), ("call_text", "Call text")], default="info", max_length=32)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="CallSession",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("goal", models.TextField()),
                ("status", models.CharField(choices=[("scheduled", "Scheduled"), ("ringing", "Ringing"), ("in_call", "In call"), ("missed", "Missed"), ("completed", "Completed"), ("canceled", "Canceled")], default="scheduled", max_length=32)),
                ("scheduled_for", models.DateTimeField(blank=True, null=True)),
                ("ringing_started_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("summary", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="CallTranscriptEntry",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("role", models.CharField(choices=[("user", "User"), ("assistant", "Assistant"), ("system", "System")], default="system", max_length=32)),
                ("content", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("session", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="transcript_entries", to="orchestration.callsession")),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="pushtoken",
            index=models.Index(fields=["platform"], name="orchestration_platform_6ffbcb_idx"),
        ),
        migrations.AddIndex(
            model_name="usermessage",
            index=models.Index(fields=["created_at"], name="orchestration_created_66b9cd_idx"),
        ),
        migrations.AddIndex(
            model_name="usermessage",
            index=models.Index(fields=["read_at"], name="orchestration_read_at_ebd22b_idx"),
        ),
        migrations.AddIndex(
            model_name="callsession",
            index=models.Index(fields=["status", "scheduled_for"], name="orchestration_status_8b2923_idx"),
        ),
        migrations.AddIndex(
            model_name="callsession",
            index=models.Index(fields=["status", "ringing_started_at"], name="orchestration_status_550906_idx"),
        ),
        migrations.AddIndex(
            model_name="calltranscriptentry",
            index=models.Index(fields=["session", "created_at"], name="orchestration_session_5b2d09_idx"),
        ),
    ]
