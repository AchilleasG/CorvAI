from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workout", "0004_remove_workoutplanexercise_workout_unique_plan_exercise_order_and_more")]
    operations = [
        migrations.AddField(model_name="exercise", name="external_provider", field=models.CharField(blank=True, default="", max_length=80)),
        migrations.AddField(model_name="exercise", name="external_id", field=models.CharField(blank=True, default="", max_length=200)),
        migrations.AddField(model_name="exercise", name="enrichment_data", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="exercise", name="demo_media_url", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="exercise", name="enriched_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="exercise", name="enrichment_error", field=models.TextField(blank=True, default="")),
    ]
