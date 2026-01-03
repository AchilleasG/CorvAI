from django.db import migrations, models
import django.contrib.postgres.fields
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0001_initial"),
        ("orchestration", "0010_user_info"),
    ]

    operations = [
        migrations.CreateModel(
            name="SoftEvent",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                ("duration_minutes", models.PositiveIntegerField(default=30)),
                ("soft_deadline", models.DateTimeField(null=True, blank=True)),
                ("hard_deadline", models.DateTimeField(null=True, blank=True)),
                (
                    "frequency",
                    models.CharField(
                        max_length=64,
                        blank=True,
                        default="",
                        help_text="Optional recurrence description (e.g., weekly, monthly).",
                    ),
                ),
                (
                    "preferred_dayparts",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=32, blank=True),
                        size=None,
                        default=list,
                        blank=True,
                        help_text="Optional preference hints such as morning/afternoon/evening.",
                    ),
                ),
                ("deferral_limit", models.PositiveIntegerField(default=3)),
                ("priority", models.IntegerField(default=0, help_text="Higher = more urgent/important.")),
                (
                    "status",
                    models.CharField(
                        max_length=32,
                        choices=[
                            ("active", "Active"),
                            ("paused", "Paused"),
                            ("archived", "Archived"),
                        ],
                        default="active",
                    ),
                ),
                ("metadata", models.JSONField(default=dict, blank=True)),
                (
                    "chat",
                    models.ForeignKey(
                        related_name="soft_events",
                        on_delete=models.deletion.SET_NULL,
                        null=True,
                        blank=True,
                        to="chat.chat",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="SoftEventSlot",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ("start_at", models.DateTimeField()),
                ("end_at", models.DateTimeField()),
                ("notify_at", models.DateTimeField(null=True, blank=True)),
                (
                    "status",
                    models.CharField(
                        max_length=32,
                        choices=[
                            ("planned", "Planned"),
                            ("completed", "Completed"),
                            ("deferred", "Deferred"),
                            ("skipped", "Skipped"),
                            ("promoted", "Promoted to calendar"),
                            ("canceled", "Canceled"),
                        ],
                        default="planned",
                    ),
                ),
                ("deferral_count", models.PositiveIntegerField(default=0)),
                ("rationale", models.TextField(blank=True, default="")),
                (
                    "planner_trace_id",
                    models.CharField(
                        max_length=255,
                        blank=True,
                        default="",
                        help_text="Correlation id from planner decisions.",
                    ),
                ),
                ("metadata", models.JSONField(default=dict, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "soft_event",
                    models.ForeignKey(
                        related_name="slots",
                        on_delete=models.deletion.CASCADE,
                        to="orchestration.softevent",
                    ),
                ),
            ],
            options={
                "ordering": ["start_at"],
            },
        ),
        migrations.AddIndex(
            model_name="softevent",
            index=models.Index(fields=["status"], name="orch_softevent_status_idx"),
        ),
        migrations.AddIndex(
            model_name="softevent",
            index=models.Index(fields=["soft_deadline"], name="orch_softevent_soft_deadline_idx"),
        ),
        migrations.AddIndex(
            model_name="softevent",
            index=models.Index(fields=["hard_deadline"], name="orch_softevent_hard_deadline_idx"),
        ),
        migrations.AddIndex(
            model_name="softevent",
            index=models.Index(fields=["priority"], name="orch_softevent_priority_idx"),
        ),
        migrations.AddIndex(
            model_name="softeventslot",
            index=models.Index(fields=["start_at"], name="orch_softeventslot_start_idx"),
        ),
        migrations.AddIndex(
            model_name="softeventslot",
            index=models.Index(fields=["status"], name="orch_softeventslot_status_idx"),
        ),
        migrations.AddIndex(
            model_name="softeventslot",
            index=models.Index(fields=["notify_at"], name="orch_softeventslot_notify_idx"),
        ),
    ]
