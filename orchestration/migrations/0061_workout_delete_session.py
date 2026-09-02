from django.db import migrations


DESCRIPTION = "Permanently delete one workout session by its exact UUID. Read workout history first to identify the intended session; never guess an ID or delete a different session."
SCHEMA = {"type":"object","properties":{"session_id":{"type":"string","description":"Exact workout session UUID returned by workout.get_history"}},"required":["session_id"]}
GUIDANCE = " When the user asks to remove a workout log, call workout.get_history first, identify the exact intended session, and pass that returned UUID to workout.delete_session. Never infer or guess a session UUID."


def configure(apps, schema_editor):
    Module = apps.get_model("orchestration", "ToolModule")
    Function = apps.get_model("orchestration", "ToolFunction")
    module = Module.objects.get(slug="workout")
    if GUIDANCE.strip() not in module.caller_instructions:
        module.caller_instructions = module.caller_instructions.rstrip() + GUIDANCE
        module.save(update_fields=["caller_instructions", "updated_at"])
    Function.objects.update_or_create(
        manifest_id="workout.delete_session",
        defaults={"module":module,"name":"Delete workout session","description":DESCRIPTION,"params_schema":SCHEMA,"return_schema":{},"handler_ref":"orchestration.tools.workout.remove_workout_session","deprecated":False,"tags":["workout"]},
    )


def remove(apps, schema_editor):
    apps.get_model("orchestration", "ToolFunction").objects.filter(manifest_id="workout.delete_session").delete()


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0060_workout_llm_exercise_resolution")]
    operations = [migrations.RunPython(configure, remove)]
