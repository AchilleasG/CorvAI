from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0023_calendar_manager_delete_soft_event"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScheduledTask",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("prompt", models.TextField()),
                ("recurrence", models.CharField(choices=[("once", "Once"), ("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")], default="once", max_length=16)),
                ("start_at", models.DateTimeField()),
                ("next_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("active", "Active"), ("paused", "Paused"), ("completed", "Completed")], default="active", max_length=16)),
                ("is_running", models.BooleanField(default=False)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["next_run_at", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ScheduledTaskRun",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("status", models.CharField(choices=[("running", "Running"), ("completed", "Completed"), ("failed", "Failed")], default="running", max_length=16)),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("summary", models.TextField(blank=True, default="")),
                ("error_summary", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("task", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="runs", to="orchestration.scheduledtask")),
            ],
            options={
                "ordering": ["-started_at"],
            },
        ),
        migrations.CreateModel(
            name="ScheduledTaskLogEntry",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("role", models.CharField(blank=True, default="system", max_length=32)),
                ("level", models.CharField(blank=True, default="info", max_length=16)),
                ("message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("run", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="log_entries", to="orchestration.scheduledtaskrun")),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="scheduledtask",
            index=models.Index(fields=["status", "next_run_at"], name="orchestration_status_8b7f4d_idx"),
        ),
        migrations.AddIndex(
            model_name="scheduledtask",
            index=models.Index(fields=["is_running"], name="orchestration_is_runn_e8d9f3_idx"),
        ),
        migrations.AddIndex(
            model_name="scheduledtaskrun",
            index=models.Index(fields=["task", "started_at"], name="orchestration_task_id_335ae6_idx"),
        ),
        migrations.AddIndex(
            model_name="scheduledtaskrun",
            index=models.Index(fields=["status"], name="orchestration_status_1df5c6_idx"),
        ),
        migrations.AddIndex(
            model_name="scheduledtasklogentry",
            index=models.Index(fields=["run", "created_at"], name="orchestration_run_id_2f0cbb_idx"),
        ),
    ]
