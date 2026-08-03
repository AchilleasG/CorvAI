import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("coding", "0001_initial")]
    operations = [
        migrations.AlterField(
            model_name="codingturn",
            name="source",
            field=models.CharField(choices=[("corv", "Corv"), ("ui", "Coding module"), ("decision", "Decision"), ("feature", "Feature delegation")], default="ui", max_length=24),
        ),
        migrations.CreateModel(
            name="FeatureDelegation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField()),
                ("acceptance_criteria", models.JSONField(default=list)),
                ("qa_enabled", models.BooleanField(default=True)),
                ("max_iterations", models.PositiveSmallIntegerField(default=6)),
                ("current_iteration", models.PositiveSmallIntegerField(default=0)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("coding", "Coding"), ("qa", "QA"), ("fixing", "Fixing"), ("needs_input", "Needs input"), ("completed", "Completed"), ("failed", "Failed"), ("stopped", "Stopped")], default="queued", max_length=24)),
                ("qa_thread_id", models.CharField(blank=True, default="", max_length=128)),
                ("coding_turn_ids", models.JSONField(blank=True, default=list)),
                ("implementation_summary", models.TextField(blank=True, default="")),
                ("qa_summary", models.TextField(blank=True, default="")),
                ("pending_question", models.TextField(blank=True, default="")),
                ("pending_options", models.JSONField(blank=True, default=list)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("stopped_at", models.DateTimeField(blank=True, null=True)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="delegations", to="coding.codingsession")),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.CreateModel(
            name="FeatureQaRun",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("iteration", models.PositiveSmallIntegerField(default=1)),
                ("status", models.CharField(choices=[("running", "Running"), ("passed", "Passed"), ("failed", "Failed"), ("blocked", "Blocked"), ("error", "Error")], default="running", max_length=24)),
                ("summary", models.TextField(blank=True, default="")),
                ("failures", models.JSONField(blank=True, default=list)),
                ("evidence", models.JSONField(blank=True, default=list)),
                ("question", models.TextField(blank=True, default="")),
                ("options", models.JSONField(blank=True, default=list)),
                ("event_log", models.TextField(blank=True, default="")),
                ("error", models.TextField(blank=True, default="")),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("delegation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="qa_runs", to="coding.featuredelegation")),
            ],
            options={"ordering": ["-started_at"]},
        ),
        migrations.AddIndex(model_name="featuredelegation", index=models.Index(fields=["session", "status"], name="coding_feat_session_7a9ca4_idx")),
        migrations.AddIndex(model_name="featureqarun", index=models.Index(fields=["delegation", "iteration"], name="coding_feat_delegat_74c1d8_idx")),
    ]
