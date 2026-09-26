from django.db import migrations


def configure(apps, schema_editor):
    from orchestration.registry import FunctionRegistry
    import orchestration.tools.workout  # noqa: F401
    Module = apps.get_model("orchestration", "ToolModule")
    Function = apps.get_model("orchestration", "ToolFunction")
    module = Module.objects.get(slug="workout")
    addition = "\n\nExercise details: use workout.get_exercise_details after list_exercises when the user asks how to perform a movement or wants technique/media. The first detail read enriches and caches public-domain instructions, muscle data, and an animated demonstration; do not force refresh unless the user asks."
    if "workout.get_exercise_details" not in module.caller_instructions:
        module.caller_instructions += addition
        module.save(update_fields=["caller_instructions", "updated_at"])
    entry = next(item for item in FunctionRegistry.all() if item.manifest_id == "workout.get_exercise_details")
    Function.objects.update_or_create(manifest_id=entry.manifest_id, defaults={"module":module,"name":entry.name or entry.manifest_id,"description":entry.description or "","params_schema":entry.params_schema or {},"return_schema":entry.return_schema or {},"handler_ref":entry.handler_ref,"deprecated":entry.deprecated,"tags":["workout"]})


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0076_full_workout_action_suite"), ("workout", "0005_exercise_enrichment")]
    operations = [migrations.RunPython(configure, migrations.RunPython.noop)]
