from django.db import migrations


def configure(apps, schema_editor):
    from orchestration.registry import FunctionRegistry
    import orchestration.tools.workout  # noqa: F401
    Module = apps.get_model("orchestration", "ToolModule")
    Function = apps.get_model("orchestration", "ToolFunction")
    module = Module.objects.get(slug="workout")
    guidance = "\n\nPlan prescriptions: every exercise in every named session must include sets and a measurable target. For rep-based work supply reps or reps_min/reps_max. For timed work supply duration_seconds or duration_seconds_min/duration_seconds_max and phase_type timed. Use per_side=true when applicable. Never leave a plan exercise with only the generic phase type."
    if "Plan prescriptions:" not in module.caller_instructions:
        module.caller_instructions += guidance
        module.save(update_fields=["caller_instructions", "updated_at"])
    entry = next(item for item in FunctionRegistry.all() if item.manifest_id == "workout.save_plan")
    Function.objects.filter(manifest_id=entry.manifest_id).update(description=entry.description, params_schema=entry.params_schema)


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0077_workout_exercise_enrichment")]
    operations = [migrations.RunPython(configure, migrations.RunPython.noop)]
