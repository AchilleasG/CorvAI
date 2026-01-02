from django.db import migrations, models
import uuid
import pgvector.django
import django.contrib.postgres.fields


def enable_pgvector(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS vector")


def disable_pgvector(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP EXTENSION IF EXISTS vector")


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0009_usageevent_costs"),
    ]

    operations = [
        migrations.RunPython(enable_pgvector, disable_pgvector),
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("user_id", models.CharField(default="default", max_length=255, primary_key=True, serialize=False)),
                ("core_text", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["user_id"],
            },
        ),
        migrations.CreateModel(
            name="UserNote",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.CharField(db_index=True, default="default", max_length=255)),
                ("content_raw", models.TextField()),
                ("content_canonical", models.TextField(blank=True, default="")),
                ("embedding", pgvector.django.VectorField(blank=True, dimensions=1536, null=True)),
                ("source", models.CharField(blank=True, default="", max_length=255)),
                (
                    "tags",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(blank=True, max_length=64), blank=True, default=list, size=None
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="usernote",
            index=models.Index(fields=["user_id", "created_at"], name="orchestrati_user_id_5765e3_idx"),
        ),
        migrations.AddIndex(
            model_name="usernote",
            index=models.Index(fields=["deleted_at"], name="orchestrati_deleted_5fb17e_idx"),
        ),
    ]
