from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workout", "0001_initial")]
    operations = [
        migrations.AddField(model_name="workoutsession", name="status", field=models.CharField(choices=[("active", "Active"), ("completed", "Completed")], db_index=True, default="completed", max_length=16)),
        migrations.AddField(model_name="workoutexerciselog", name="completed", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="workoutexerciselog", name="completed_at", field=models.DateTimeField(blank=True, null=True)),
    ]
