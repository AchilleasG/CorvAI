from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0005_chat_archived"),
        ("orchestration", "0039_rename_orchestration_status_8b2923_idx_orchestrati_status_242133_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Objective",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("active", "Active"), ("completed", "Completed"), ("paused", "Paused"), ("canceled", "Canceled")], default="active", max_length=32)),
                ("deadline_at", models.DateTimeField(blank=True, null=True)),
                ("estimated_effort_minutes", models.PositiveIntegerField(blank=True, null=True)),
                ("remaining_effort_minutes", models.PositiveIntegerField(blank=True, null=True)),
                ("priority", models.IntegerField(default=0)),
                ("notes", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("chat", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="objectives", to="chat.chat")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="children", to="orchestration.objective")),
            ],
            options={
                "ordering": ["deadline_at", "-priority", "created_at"],
            },
        ),
        migrations.CreateModel(
            name="ObjectiveTask",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("todo", "To Do"), ("in_progress", "In Progress"), ("done", "Done"), ("blocked", "Blocked"), ("canceled", "Canceled")], default="todo", max_length=32)),
                ("estimated_effort_minutes", models.PositiveIntegerField(blank=True, null=True)),
                ("remaining_effort_minutes", models.PositiveIntegerField(blank=True, null=True)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("objective", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tasks", to="orchestration.objective")),
            ],
            options={
                "ordering": ["objective", "sort_order", "created_at"],
            },
        ),
        migrations.CreateModel(
            name="ObjectiveLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("work", "Work"), ("note", "Note"), ("progress", "Progress"), ("decision", "Decision"), ("blocker", "Blocker")], default="note", max_length=32)),
                ("text", models.TextField(blank=True, default="")),
                ("minutes_spent", models.PositiveIntegerField(blank=True, null=True)),
                ("logged_at", models.DateTimeField(auto_now_add=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("objective", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="logs", to="orchestration.objective")),
                ("task", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="logs", to="orchestration.objectivetask")),
            ],
            options={
                "ordering": ["-logged_at", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="SoftEventObjective",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("role", models.CharField(choices=[("primary", "Primary"), ("secondary", "Secondary")], default="primary", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("objective", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="soft_event_links", to="orchestration.objective")),
                ("soft_event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="objective_links", to="orchestration.softevent")),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.CreateModel(
            name="SoftEventTask",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("soft_event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="task_links", to="orchestration.softevent")),
                ("task", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="soft_event_links", to="orchestration.objectivetask")),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="objective",
            index=models.Index(fields=["status"], name="orchestrati_status_90cf1d_idx"),
        ),
        migrations.AddIndex(
            model_name="objective",
            index=models.Index(fields=["deadline_at"], name="orchestrati_deadlin_3d1541_idx"),
        ),
        migrations.AddIndex(
            model_name="objective",
            index=models.Index(fields=["priority"], name="orchestrati_priorit_ae8016_idx"),
        ),
        migrations.AddIndex(
            model_name="objective",
            index=models.Index(fields=["parent"], name="orchestrati_parent__a05021_idx"),
        ),
        migrations.AddIndex(
            model_name="objectivetask",
            index=models.Index(fields=["objective", "status"], name="orchestrati_objecti_f50486_idx"),
        ),
        migrations.AddIndex(
            model_name="objectivetask",
            index=models.Index(fields=["due_at"], name="orchestrati_due_at_9e4b6f_idx"),
        ),
        migrations.AddIndex(
            model_name="objectivelog",
            index=models.Index(fields=["objective", "logged_at"], name="orchestrati_objecti_f3ee47_idx"),
        ),
        migrations.AddIndex(
            model_name="objectivelog",
            index=models.Index(fields=["kind"], name="orchestrati_kind_681617_idx"),
        ),
        migrations.AddConstraint(
            model_name="softeventobjective",
            constraint=models.UniqueConstraint(fields=("soft_event", "objective"), name="unique_soft_event_objective_link"),
        ),
        migrations.AddIndex(
            model_name="softeventobjective",
            index=models.Index(fields=["objective", "role"], name="orchestrati_objecti_01e7f5_idx"),
        ),
        migrations.AddConstraint(
            model_name="softeventtask",
            constraint=models.UniqueConstraint(fields=("soft_event", "task"), name="unique_soft_event_task_link"),
        ),
        migrations.AddIndex(
            model_name="softeventtask",
            index=models.Index(fields=["task"], name="orchestrati_task_id_8397a1_idx"),
        ),
    ]
