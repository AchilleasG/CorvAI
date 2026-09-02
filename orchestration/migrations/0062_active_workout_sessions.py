from django.db import migrations


FUNCTIONS = [
    ("workout.start_session", "Start workout session", "Start an in-progress workout from a saved plan or exercise list and create its checklist.", "orchestration.tools.workout.begin_workout_session", {"type":"object","properties":{"plan":{"type":"string"},"title":{"type":"string"},"started_at":{"type":"string"},"notes":{"type":"string"},"exercises":{"type":"array","items":{"type":"object"}},"metadata":{"type":"object"}}}),
    ("workout.get_active_sessions", "Get active workout sessions", "View in-progress workout sessions and checklist completion.", "orchestration.tools.workout.get_active_workout_sessions", {"type":"object","properties":{}}),
    ("workout.update_session_item", "Update workout checklist item", "Check or uncheck an exercise and record actual performance.", "orchestration.tools.workout.change_workout_item", {"type":"object","properties":{"log_id":{"type":"string"},"completed":{"type":"boolean"},"sets":{"type":"integer"},"reps":{"type":"integer"},"weight_kg":{"type":"number"},"duration_seconds":{"type":"integer"},"distance_km":{"type":"number"},"rpe":{"type":"number"},"notes":{"type":"string"},"metadata":{"type":"object"}},"required":["log_id"]}),
    ("workout.finish_session", "Finish workout session", "Finish an active workout while preserving its checklist and recorded actual performance.", "orchestration.tools.workout.complete_workout_session", {"type":"object","properties":{"session_id":{"type":"string"},"ended_at":{"type":"string"},"notes":{"type":"string"}},"required":["session_id"]}),
]
GUIDANCE = " When the user wants to work through a workout in real time, use workout.start_session rather than logging it as already completed. Use workout.get_active_sessions to report the current checklist, workout.update_session_item as exercises are completed or measurements change, and workout.finish_session only when the user says the workout is done."


def configure(apps, schema_editor):
    Module = apps.get_model("orchestration", "ToolModule")
    Function = apps.get_model("orchestration", "ToolFunction")
    module = Module.objects.get(slug="workout")
    if GUIDANCE.strip() not in module.caller_instructions:
        module.caller_instructions = module.caller_instructions.rstrip() + GUIDANCE
        module.save(update_fields=["caller_instructions", "updated_at"])
    for manifest, name, description, handler, schema in FUNCTIONS:
        Function.objects.update_or_create(manifest_id=manifest, defaults={"module":module,"name":name,"description":description,"params_schema":schema,"return_schema":{},"handler_ref":handler,"deprecated":False,"tags":["workout"]})


def remove(apps, schema_editor):
    apps.get_model("orchestration", "ToolFunction").objects.filter(manifest_id__in=[row[0] for row in FUNCTIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0061_workout_delete_session"), ("workout", "0002_active_sessions")]
    operations = [migrations.RunPython(configure, remove)]
