from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0018_calendar_manager_module"),
        ("study", "0014_make_assignment_objective_nullable"),
    ]

    operations = [
        migrations.CreateModel(
            name="StudyTopicAudiobookVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("version_number", models.PositiveIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("ready", "Ready"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("generation_notes", models.TextField(blank=True, default="")),
                ("script_markdown", models.TextField(blank=True, default="")),
                ("audio_file", models.FileField(blank=True, null=True, upload_to="study/audiobooks/")),
                ("audio_mime_type", models.CharField(blank=True, default="audio/mpeg", max_length=64)),
                ("tts_voice", models.CharField(blank=True, default="alloy", max_length=64)),
                ("tts_model", models.CharField(blank=True, default="gpt-4o-mini-tts", max_length=128)),
                ("processing_error", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "job",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="study_topic_audiobooks",
                        to="orchestration.job",
                    ),
                ),
                (
                    "topic",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audiobook_versions",
                        to="study.studytopic",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="studytopicaudiobookversion",
            constraint=models.UniqueConstraint(fields=("topic", "version_number"), name="unique_topic_audiobook_version"),
        ),
        migrations.AddIndex(
            model_name="studytopicaudiobookversion",
            index=models.Index(fields=["topic", "created_at"], name="study_study_topic_idx"),
        ),
        migrations.AddIndex(
            model_name="studytopicaudiobookversion",
            index=models.Index(fields=["status"], name="study_study_status_0d468d_idx"),
        ),
    ]
