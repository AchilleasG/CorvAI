from django.db import migrations, models


def forwards(apps, schema_editor):
    StudyMaterial = apps.get_model("study", "StudyMaterial")
    StudyMaterial.objects.filter(kind="lecture_pdf").update(kind="lecture")


def backwards(apps, schema_editor):
    StudyMaterial = apps.get_model("study", "StudyMaterial")
    StudyMaterial.objects.filter(kind="lecture").update(kind="lecture_pdf")


class Migration(migrations.Migration):
    dependencies = [
        ("study", "0007_update_study_tool_expansion_topics"),
    ]

    operations = [
        migrations.AlterField(
            model_name="studymaterial",
            name="kind",
            field=models.CharField(
                choices=[
                    ("lecture", "Lecture"),
                    ("slides", "Slides"),
                    ("past_exam", "Past Exam"),
                    ("notes", "Notes"),
                    ("link", "Link"),
                    ("other", "Other"),
                ],
                default="other",
                max_length=32,
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
