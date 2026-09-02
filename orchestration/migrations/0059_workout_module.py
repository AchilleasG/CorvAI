from django.db import migrations

FUNCTIONS = [
    ("workout.list_exercises", "List exercises", "Search the expandable workout exercise directory before suggesting or logging movements.", {"type":"object","properties":{"query":{"type":"string"}}}),
    ("workout.save_plan", "Save workout plan", "Create or import a workout plan; resolve known exercises and create missing directory entries.", {"type":"object","properties":{"title":{"type":"string"},"description":{"type":"string"},"goal":{"type":"string"},"source":{"type":"string"},"schedule":{"type":"object"},"exercises":{"type":"array","items":{"type":"object"}},"metadata":{"type":"object"}},"required":["title","exercises"]}),
    ("workout.list_plans", "List workout plans", "List saved workout plans and exercise prescriptions.", {"type":"object","properties":{"active_only":{"type":"boolean"}}}),
    ("workout.log_session", "Log workout session", "Log a workout with date/time, exercises, kilos, duration, reps, sets, distance, RPE, notes, and metadata; create missing exercises.", {"type":"object","properties":{"title":{"type":"string"},"plan":{"type":"string"},"started_at":{"type":"string"},"ended_at":{"type":"string"},"notes":{"type":"string"},"exercises":{"type":"array","items":{"type":"object"}},"metadata":{"type":"object"}},"required":["exercises"]}),
    ("workout.get_history", "Get workout history", "Read logged workout sessions filtered by date or exercise.", {"type":"object","properties":{"start_date":{"type":"string"},"end_date":{"type":"string"},"exercise":{"type":"string"},"limit":{"type":"integer"}}}),
    ("workout.get_progress", "Get workout progress", "Get consistency, streaks, goals, and time-series exercise progress.", {"type":"object","properties":{"days":{"type":"integer"},"exercise":{"type":"string"}}}),
    ("workout.set_goal", "Set workout goal", "Create a workout consistency or exercise-progress goal.", {"type":"object","properties":{"title":{"type":"string"},"metric":{"type":"string"},"target_value":{"type":"number"},"unit":{"type":"string"},"exercise":{"type":"string"},"start_date":{"type":"string"},"end_date":{"type":"string"},"metadata":{"type":"object"}},"required":["title","metric","target_value"]}),
]

def create_module(apps, schema_editor):
    Module=apps.get_model("orchestration","ToolModule"); Function=apps.get_model("orchestration","ToolFunction")
    module,_=Module.objects.update_or_create(slug="workout",defaults={"name":"Workout","description":"Create and import workout plans, maintain an exercise directory, log training, and track progress and consistency.","tags":["fitness","exercise","health","progress"],"caller_instructions":"Use this module whenever the user discusses training plans, exercises, sets, reps, weight, duration, workout logs, streaks, or fitness consistency. When logging, pass every mentioned exercise to log_session: it resolves existing entries and creates missing ones. Preserve the user's stated date/time and all provided metadata. Never invent completed sessions or measurements."})
    handlers = {"workout.save_plan": "save_workout_plan", "workout.log_session": "log_workout_session"}
    for manifest,name,description,schema in FUNCTIONS:
        handler = handlers.get(manifest, manifest.split(".")[-1])
        Function.objects.update_or_create(manifest_id=manifest,defaults={"module":module,"name":name,"description":description,"params_schema":schema,"return_schema":{},"handler_ref":f"orchestration.tools.workout.{handler}","deprecated":False,"tags":["workout"]})

def remove_module(apps, schema_editor):
    apps.get_model("orchestration","ToolModule").objects.filter(slug="workout").delete()

class Migration(migrations.Migration):
    dependencies=[("orchestration","0058_codex_first_discovery"),("workout","0001_initial")]
    operations=[migrations.RunPython(create_module,remove_module)]
