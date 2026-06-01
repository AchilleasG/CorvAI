from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0042_soft_slot_outcome_functions"),
        ("study", "0013_studyassignment_uploaded_file"),
    ]

    operations = [
        migrations.AlterField(
            model_name="studyassignment",
            name="objective",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="study_assignment",
                to="orchestration.objective",
            ),
        ),
    ]
