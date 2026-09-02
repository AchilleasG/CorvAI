from django.db import migrations


FUNCTIONS = [
    ("workout.delete_plan", "Delete workout plan", "Delete a saved workout plan by exact UUID while preserving historical sessions.", "orchestration.tools.workout.remove_workout_plan", {"type":"object","properties":{"plan_id":{"type":"string"}},"required":["plan_id"]}),
    ("workout.delete_exercise", "Delete exercise", "Delete an exercise by exact UUID. Referenced entries require explicit delete_references confirmation.", "orchestration.tools.workout.remove_workout_exercise", {"type":"object","properties":{"exercise_id":{"type":"string"},"delete_references":{"type":"boolean"}},"required":["exercise_id"]}),
]
GUIDANCE = " To delete a workout plan or exercise, list the corresponding records first and use the exact returned UUID. Deleting a plan preserves historical sessions. Never set delete_references for an exercise unless the user explicitly agrees that its plan items and historical workout log items should also be removed."


def configure(apps,schema_editor):
    Module=apps.get_model("orchestration","ToolModule"); Function=apps.get_model("orchestration","ToolFunction"); module=Module.objects.get(slug="workout")
    if GUIDANCE.strip() not in module.caller_instructions:
        module.caller_instructions=module.caller_instructions.rstrip()+GUIDANCE; module.save(update_fields=["caller_instructions","updated_at"])
    for manifest,name,description,handler,schema in FUNCTIONS:
        Function.objects.update_or_create(manifest_id=manifest,defaults={"module":module,"name":name,"description":description,"params_schema":schema,"return_schema":{},"handler_ref":handler,"deprecated":False,"tags":["workout"]})


def remove(apps,schema_editor): apps.get_model("orchestration","ToolFunction").objects.filter(manifest_id__in=[row[0] for row in FUNCTIONS]).delete()


class Migration(migrations.Migration):
    dependencies=[("orchestration","0062_active_workout_sessions")]
    operations=[migrations.RunPython(configure,remove)]
