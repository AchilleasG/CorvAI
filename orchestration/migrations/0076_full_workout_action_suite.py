from django.db import migrations


CALLER_INSTRUCTIONS = """Use the workout module for the full training lifecycle: exercise-directory CRUD, plans and named planned sessions, live guided/checklist workouts, detailed per-set logging, history corrections, goals, and progress.

Directory safety: the LLM must inspect workout.list_exercises first before creating, renaming, planning with, or logging an exercise, call workout.list_exercises (use an empty query when needed) and use LLM semantic judgment to reuse the best canonical movement. Do not rely on exact strings and do not create near-duplicates. Use workout.create_exercise only when no existing entry fits; use workout.update_exercise for corrections.

ID safety: list/read the relevant exercises, plans, active sessions, history, or goals before update/delete calls. Use only exact returned UUIDs; never guess one.

Plans: represent programs as named sessions. Exercises may be reps-based or timed, may have optional rest_seconds, simple sets or set_targets, and one-level cycle blocks using block_name/block_key and cycle_count. workout.update_plan preserves programming when exercises and sessions are omitted. Supplying either replaces the complete programming, so include every item that must remain.

Sessions: workout.log_session records an already performed workout. workout.start_session starts an interactive workout; when a plan has named sessions pass the intended planned_session UUID and choose checklist/guided plus minimal/full guidance. During a live workout use update_session_item/update_set and change_session_state. Finish with draft=true when a report should be reviewed, then use edit_session/edit_exercise_log/edit_set_log as needed and change_session_state submit. Historical corrections use those edit actions too.

Goals: list goals before updating, archiving, or deleting. Prefer active=false for archive; delete only when explicitly requested.

Preserve objective ISO dates/times and every user-provided measurement. Never invent completed work, reps, load, duration, distance, RPE, or timestamps. If a materially ambiguous value would change the record, ask rather than guessing."""


def configure(apps, schema_editor):
    from orchestration.registry import FunctionRegistry
    import orchestration.tools.workout  # noqa: F401
    Module=apps.get_model("orchestration","ToolModule")
    Function=apps.get_model("orchestration","ToolFunction")
    module=Module.objects.get(slug="workout")
    module.caller_instructions=CALLER_INSTRUCTIONS
    module.description="Complete workout management: exercise directory, multi-session plans, guided/checklist execution, detailed logs, goals, history, and progress."
    module.save(update_fields=["caller_instructions","description","updated_at"])
    for entry in FunctionRegistry.all():
        if entry.module != "workout": continue
        Function.objects.update_or_create(manifest_id=entry.manifest_id,defaults={"module":module,"name":entry.name or entry.manifest_id,"description":entry.description or "","params_schema":entry.params_schema or {},"return_schema":entry.return_schema or {},"handler_ref":entry.handler_ref,"deprecated":entry.deprecated,"tags":["workout"]})


class Migration(migrations.Migration):
    dependencies=[("orchestration","0075_text_markdown_presentation"),("workout","0003_workoutexerciselog_block_key_and_more")]
    operations=[migrations.RunPython(configure,migrations.RunPython.noop)]
