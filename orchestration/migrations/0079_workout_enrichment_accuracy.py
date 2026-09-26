from django.db import migrations


GUIDANCE = """

Exercise-data accuracy:
- Automatic enrichment is confidence-gated. Treat an enrichment_error or a missing field as unknown; never present a similar movement as if it were the requested exercise.
- Use workout.get_enrichment_issues to find incomplete directory entries.
- For an incomplete exercise, search the internet for reliable, exercise-specific sources, verify that the source describes the exact same movement, and then save verified fields and source provenance in metadata with workout.update_exercise.
- Prefer no animation over an animation of a different movement. Clearly disclose when media is only a close visual variant.
- Manual and Corv edits are preserved as enrichment overrides on later provider refreshes.
"""


def configure(apps, schema_editor):
    from orchestration.registry import FunctionRegistry
    import orchestration.tools.workout  # noqa: F401
    Module = apps.get_model("orchestration", "ToolModule")
    Function = apps.get_model("orchestration", "ToolFunction")
    module = Module.objects.get(slug="workout")
    if "Exercise-data accuracy:" not in module.caller_instructions:
        module.caller_instructions += GUIDANCE
        module.save(update_fields=["caller_instructions", "updated_at"])
    entry = next(item for item in FunctionRegistry.all() if item.manifest_id == "workout.get_enrichment_issues")
    Function.objects.update_or_create(manifest_id=entry.manifest_id, defaults={"module": module, "name": entry.name or entry.manifest_id, "description": entry.description or "", "params_schema": entry.params_schema or {}, "return_schema": entry.return_schema or {}, "handler_ref": entry.handler_ref, "deprecated": entry.deprecated, "tags": ["workout"]})


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0078_workout_prescription_ranges")]
    operations = [migrations.RunPython(configure, migrations.RunPython.noop)]
