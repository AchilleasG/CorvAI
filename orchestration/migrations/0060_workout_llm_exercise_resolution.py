from django.db import migrations


CALLER_INSTRUCTIONS = """Use this module whenever the user discusses training plans, exercises, sets, reps, weight, duration, workout logs, streaks, or fitness consistency. For every workout log or imported plan, the LLM must inspect workout.list_exercises first (use an empty query when a narrow search may miss related names), understand the user's movement semantically, and choose the best existing canonical exercise name when appropriate. Do not rely on literal string matching and do not create aliases or near-duplicate exercises merely because the user's wording differs. Pass a new exercise name only when your semantic review finds no suitable directory entry; workout.log_session or workout.save_plan will then create it. Preserve the user's stated date/time and all provided metadata. Never invent completed sessions or measurements."""

LIST_DESCRIPTION = "Inspect the exercise directory so you can semantically match the user's wording to the best existing canonical exercise. Search broadly or list all entries before logging; do not create a near-duplicate."
LOG_DESCRIPTION = "Log a completed or ongoing workout session after inspecting the exercise directory and using LLM judgment to map every mentioned movement to an existing canonical exercise name. Only pass a new name when no existing entry is semantically appropriate; the logger creates it. Include date/time and optional sets, reps, kilos, duration, distance, RPE, notes, and metadata."
PLAN_DESCRIPTION = "Create or import a workout plan after inspecting the exercise directory and using LLM judgment to map movements to existing canonical entries. Only unmatched exercises should be created."


def configure(apps, schema_editor):
    Module = apps.get_model("orchestration", "ToolModule")
    Function = apps.get_model("orchestration", "ToolFunction")
    module = Module.objects.get(slug="workout")
    module.caller_instructions = CALLER_INSTRUCTIONS
    module.save(update_fields=["caller_instructions", "updated_at"])
    descriptions = {
        "workout.list_exercises": LIST_DESCRIPTION,
        "workout.log_session": LOG_DESCRIPTION,
        "workout.save_plan": PLAN_DESCRIPTION,
    }
    for manifest_id, description in descriptions.items():
        item = Function.objects.get(manifest_id=manifest_id)
        item.description = description
        item.save(update_fields=["description", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0059_workout_module")]
    operations = [migrations.RunPython(configure, migrations.RunPython.noop)]
