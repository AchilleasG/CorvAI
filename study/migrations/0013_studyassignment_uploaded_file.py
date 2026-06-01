from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("study", "0012_study_objectives"),
    ]

    operations = [
        migrations.AddField(
            model_name="studyassignment",
            name="uploaded_file",
            field=models.FileField(blank=True, null=True, upload_to="study/assignments/"),
        ),
    ]
