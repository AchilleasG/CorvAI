from __future__ import annotations

from django.db.models import Q

from orchestration.registry import register_function
from workout.models import Exercise, WorkoutGoal, WorkoutPlan
from workout.services import active_sessions, dashboard, delete_exercise, delete_goal_record, delete_plan, delete_session, edit_any_set_log, edit_exercise_log, edit_session, enrich_exercise, enrichment_issues, exercise_payload, finish_session, goal_payload, history, list_goals as list_goal_records, log_session, plan_payload, resolve_exercise, save_plan, set_session_status, start_session, update_exercise, update_goal_record, update_plan, update_session_item, update_set_log


EXERCISE_ITEM = {
    "type": "object",
    "properties": {
        "name": {"type": "string"}, "sets": {"type": "integer"}, "reps": {"type": ["integer", "string"]},
        "reps_min": {"type": "integer"}, "reps_max": {"type": "integer"},
        "weight_kg": {"type": "number"}, "duration_seconds": {"type": "integer"}, "distance_km": {"type": "number"},
        "duration_seconds_min": {"type": "integer"}, "duration_seconds_max": {"type": "integer"}, "per_side": {"type": "boolean"},
        "rest_seconds": {"type": "integer"}, "rpe": {"type": "number"}, "notes": {"type": "string"},
        "category": {"type": "string"}, "muscle_group": {"type": "string"}, "equipment": {"type": "string"},
        "metadata": {"type": "object"},
        "phase_type": {"type":"string","enum":["reps","timed"]}, "set_targets": {"type":"array","items":{"type":"object"}},
        "block_key": {"type":"string"}, "block_name": {"type":"string"}, "cycle_count": {"type":"integer","minimum":1},
    },
    "required": ["name"],
}


@register_function(manifest_id="workout.list_exercises", module="workout", description="Inspect the exercise directory so you can semantically match the user's wording to the best existing canonical exercise. Search broadly or list all entries before logging; do not create a near-duplicate.", params_schema={"type":"object","properties":{"query":{"type":"string"}}})
def list_exercises(query: str=""):
    qs=Exercise.objects.all()
    if query: qs=qs.filter(Q(name__icontains=query)|Q(category__icontains=query)|Q(muscle_group__icontains=query))
    return {"exercises":[exercise_payload(item) for item in qs[:100]]}


@register_function(manifest_id="workout.create_exercise", module="workout", description="Create one standalone exercise-directory entry after searching the directory semantically and confirming no existing exercise represents the same movement.", params_schema={"type":"object","properties":{"name":{"type":"string"},"aliases":{"type":"array","items":{"type":"string"}},"category":{"type":"string"},"muscle_group":{"type":"string"},"equipment":{"type":"string"},"instructions":{"type":"string"},"metadata":{"type":"object"}},"required":["name"]})
def create_workout_exercise(name: str, aliases=None, category="", muscle_group="", equipment="", instructions="", metadata=None):
    item,created=resolve_exercise(name,defaults={"aliases":aliases or [],"category":category,"muscle_group":muscle_group,"equipment":equipment,"instructions":instructions,"metadata":metadata or {}})
    return {**exercise_payload(item),"created":created}


@register_function(manifest_id="workout.update_exercise", module="workout", description="Edit an existing exercise-directory entry by exact UUID. List exercises first; never guess the ID. Use this for canonical name, aliases, category, muscle group, equipment, instructions, or metadata.", params_schema={"type":"object","properties":{"exercise_id":{"type":"string"},"name":{"type":"string"},"aliases":{"type":"array","items":{"type":"string"}},"category":{"type":"string"},"muscle_group":{"type":"string"},"equipment":{"type":"string"},"instructions":{"type":"string"},"metadata":{"type":"object"}},"required":["exercise_id"]})
def edit_workout_exercise(exercise_id: str, **changes): return update_exercise(exercise_id,**changes)


@register_function(manifest_id="workout.get_exercise_details", module="workout", description="Get saved technique details and a locally cached animated demonstration for an exercise UUID. Automated enrichment only accepts an exact name or reviewed alias. If enrichment_error is present or fields are missing, never guess: search reliable exercise-specific internet sources, verify the exact movement, then save accurate findings with workout.update_exercise. List exercises first and use its exact UUID.", params_schema={"type":"object","properties":{"exercise_id":{"type":"string"},"refresh":{"type":"boolean"}},"required":["exercise_id"]})
def get_workout_exercise_details(exercise_id: str, refresh: bool=False): return enrich_exercise(exercise_id, force=refresh)


@register_function(manifest_id="workout.get_enrichment_issues", module="workout", description="List exercises with missing technique, muscle, equipment, demo, or failed automatic enrichment. Research reliable exercise-specific internet sources and update only verified fields; never substitute a merely similar movement.", params_schema={"type":"object","properties":{}})
def get_workout_enrichment_issues(): return {"exercises": enrichment_issues()}


@register_function(manifest_id="workout.save_plan", module="workout", description="Create or import a workout plan using named planned sessions. Every exercise must include sets plus reps/reps_min+reps_max for rep work, or duration_seconds/duration_seconds_min+duration_seconds_max for timed work. Set phase_type timed for timed work and per_side when applicable. Optional rest, per-set targets, and cycle blocks are supported. Exercise names resolve to the directory and missing exercises are created.", params_schema={"type":"object","properties":{"title":{"type":"string"},"description":{"type":"string"},"goal":{"type":"string"},"source":{"type":"string","enum":["corv","import","manual"]},"schedule":{"type":"object"},"exercises":{"type":"array","items":EXERCISE_ITEM},"sessions":{"type":"array","items":{"type":"object","properties":{"name":{"type":"string"},"description":{"type":"string"},"guidance_mode":{"type":"string","enum":["checklist","guided"]},"guidance_level":{"type":"string","enum":["minimal","full"]},"auto_start_phases":{"type":"boolean"},"exercises":{"type":"array","items":EXERCISE_ITEM}},"required":["name","exercises"]}},"metadata":{"type":"object"}},"required":["title"]})
def save_workout_plan(title: str, exercises: list[dict]|None=None, sessions: list[dict]|None=None, description: str="", goal: str="", source: str="corv", schedule: dict|None=None, metadata: dict|None=None):
    return save_plan(title=title,exercises=exercises or [],sessions=sessions or [],description=description,goal=goal,source=source,schedule=schedule or {},metadata=metadata or {})


@register_function(manifest_id="workout.list_plans", module="workout", description="List saved workout plans with their exercise prescriptions.", params_schema={"type":"object","properties":{"active_only":{"type":"boolean"}}})
def list_plans(active_only: bool=False):
    qs=WorkoutPlan.objects.prefetch_related("plan_exercises__exercise"); qs=qs.filter(active=True) if active_only else qs
    return {"plans":[plan_payload(item) for item in qs[:100]]}


@register_function(manifest_id="workout.update_plan", module="workout", description="Edit a workout plan by exact UUID. List plans first. Omit exercises/sessions to preserve programming; when either is supplied, the complete plan programming is replaced, so include every exercise and named session that must remain.", params_schema={"type":"object","properties":{"plan_id":{"type":"string"},"title":{"type":"string"},"description":{"type":"string"},"goal":{"type":"string"},"schedule":{"type":"object"},"active":{"type":"boolean"},"metadata":{"type":"object"},"exercises":{"type":"array","items":EXERCISE_ITEM},"sessions":{"type":"array","items":{"type":"object"}}},"required":["plan_id"]})
def edit_workout_plan(plan_id: str, title=None, description=None, goal=None, schedule=None, active=None, metadata=None, exercises=None, sessions=None):
    return update_plan(plan_id,title=title,description=description,goal=goal,schedule=schedule,active=active,metadata=metadata,exercises=exercises,sessions=sessions)


@register_function(manifest_id="workout.log_session", module="workout", description="Log a completed or ongoing workout session after LLM judgment has semantically inspected the exercise directory to map each mentioned movement to an existing canonical exercise name. Only pass a new name when no existing entry is semantically appropriate; the logger then creates it. Include date/time and optional sets, reps, kilos, duration, distance, RPE, notes, and arbitrary metadata.", params_schema={"type":"object","properties":{"title":{"type":"string"},"plan":{"type":"string"},"started_at":{"type":"string","description":"ISO datetime; defaults to now"},"ended_at":{"type":"string"},"notes":{"type":"string"},"exercises":{"type":"array","items":EXERCISE_ITEM},"metadata":{"type":"object"}},"required":["exercises"]})
def log_workout_session(exercises: list[dict], started_at: str="", ended_at: str="", plan: str="", title: str="", notes: str="", metadata: dict|None=None):
    return log_session(exercises=exercises,started_at=started_at or None,ended_at=ended_at or None,plan=plan or None,title=title,notes=notes,metadata=metadata or {})


@register_function(manifest_id="workout.get_history", module="workout", description="Read logged workout history, optionally filtered by dates or exercise.", params_schema={"type":"object","properties":{"start_date":{"type":"string"},"end_date":{"type":"string"},"exercise":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":500}}})
def get_history(start_date: str="", end_date: str="", exercise: str="", limit: int=100):
    return {"sessions":history(start_date=start_date or None,end_date=end_date or None,exercise=exercise or None,limit=limit)}


@register_function(manifest_id="workout.start_session", module="workout", description="Start an in-progress workout from a saved plan/named planned session or an ad-hoc exercise list. Use planned_session UUID when the plan has multiple days. Choose checklist or guided mode and minimal or full guidance.", params_schema={"type":"object","properties":{"plan":{"type":"string"},"planned_session":{"type":"string"},"title":{"type":"string"},"started_at":{"type":"string"},"notes":{"type":"string"},"mode":{"type":"string","enum":["checklist","guided"]},"guidance_level":{"type":"string","enum":["minimal","full"]},"exercises":{"type":"array","items":EXERCISE_ITEM},"metadata":{"type":"object"}}})
def begin_workout_session(plan: str="", planned_session: str="", exercises: list[dict]|None=None, title: str="", started_at: str="", notes: str="", mode="checklist", guidance_level="minimal", metadata: dict|None=None):
    return start_session(plan=plan or None,planned_session=planned_session or None,exercises=exercises or [],title=title,started_at=started_at or None,notes=notes,mode=mode,guidance_level=guidance_level,metadata=metadata or {})


@register_function(manifest_id="workout.get_active_sessions", module="workout", description="View all in-progress workout sessions and their exercise checklist completion state.", params_schema={"type":"object","properties":{}})
def get_active_workout_sessions(): return {"sessions": active_sessions()}


@register_function(manifest_id="workout.update_session_item", module="workout", description="Check or uncheck an exercise in an active workout and optionally record actual sets, reps, kilos, duration, distance, RPE, notes, or metadata.", params_schema={"type":"object","properties":{"log_id":{"type":"string"},"completed":{"type":"boolean"},"sets":{"type":"integer"},"reps":{"type":"integer"},"weight_kg":{"type":"number"},"duration_seconds":{"type":"integer"},"distance_km":{"type":"number"},"rpe":{"type":"number"},"notes":{"type":"string"},"metadata":{"type":"object"}},"required":["log_id"]})
def change_workout_item(log_id: str, completed=None, sets=None, reps=None, weight_kg=None, duration_seconds=None, distance_km=None, rpe=None, notes=None, metadata=None):
    return update_session_item(log_id, completed=completed, sets=sets, reps=reps, weight_kg=weight_kg, duration_seconds=duration_seconds, distance_km=distance_km, rpe=rpe, notes=notes, metadata=metadata)


@register_function(manifest_id="workout.update_set", module="workout", description="Update one set in an active workout with its completion state and detailed actual reps, load, duration, distance, RPE, or notes.", params_schema={"type":"object","properties":{"set_id":{"type":"string"},"status":{"type":"string","enum":["pending","active","completed","skipped"]},"actual":{"type":"object"},"notes":{"type":"string"}},"required":["set_id"]})
def change_workout_set(set_id: str, status=None, actual=None, notes=None): return update_set_log(set_id,status=status,actual=actual,notes=notes)


@register_function(manifest_id="workout.edit_session", module="workout", description="Edit title, notes, timestamps, or metadata for any active or historical workout session by exact UUID. Read active sessions or history first.", params_schema={"type":"object","properties":{"session_id":{"type":"string"},"title":{"type":"string"},"notes":{"type":"string"},"started_at":{"type":"string"},"ended_at":{"type":"string"},"metadata":{"type":"object"}},"required":["session_id"]})
def edit_workout_session(session_id: str, **changes): return edit_session(session_id,**changes)


@register_function(manifest_id="workout.edit_exercise_log", module="workout", description="Correct an exercise log in an active or completed session by exact log UUID. Read the session first; never guess IDs.", params_schema={"type":"object","properties":{"log_id":{"type":"string"},"exercise":{"type":"string"},"sets":{"type":"integer"},"reps":{"type":"integer"},"weight_kg":{"type":"number"},"duration_seconds":{"type":"integer"},"distance_km":{"type":"number"},"rpe":{"type":"number"},"notes":{"type":"string"},"metadata":{"type":"object"}},"required":["log_id"]})
def edit_workout_exercise_log(log_id: str, **changes): return edit_exercise_log(log_id,**changes)


@register_function(manifest_id="workout.edit_set_log", module="workout", description="Correct a detailed per-set target, actual result, status, or notes in any active or historical workout by exact set UUID.", params_schema={"type":"object","properties":{"set_id":{"type":"string"},"status":{"type":"string","enum":["pending","active","completed","skipped"]},"target":{"type":"object"},"actual":{"type":"object"},"notes":{"type":"string"}},"required":["set_id"]})
def edit_workout_set_log(set_id: str, **changes): return edit_any_set_log(set_id,**changes)


@register_function(manifest_id="workout.change_session_state", module="workout", description="Pause, resume, submit the reviewed draft report, or abandon an in-progress workout.", params_schema={"type":"object","properties":{"session_id":{"type":"string"},"action":{"type":"string","enum":["pause","resume","submit","abandon"]}},"required":["session_id","action"]})
def change_workout_session_state(session_id: str, action: str): return set_session_status(session_id,action)


@register_function(manifest_id="workout.finish_session", module="workout", description="Finish an active workout. Set draft true when the user should review/edit the report before submitting; otherwise commit it directly to history.", params_schema={"type":"object","properties":{"session_id":{"type":"string"},"ended_at":{"type":"string"},"notes":{"type":"string"},"draft":{"type":"boolean"}},"required":["session_id"]})
def complete_workout_session(session_id: str, ended_at: str="", notes=None, draft=False): return finish_session(session_id,ended_at=ended_at or None,notes=notes,draft=draft)


@register_function(manifest_id="workout.delete_plan", module="workout", description="Delete one saved workout plan by exact UUID. Historical sessions are preserved and become independent of the deleted plan. List plans first and never guess the ID.", params_schema={"type":"object","properties":{"plan_id":{"type":"string"}},"required":["plan_id"]})
def remove_workout_plan(plan_id: str): return delete_plan(plan_id)


@register_function(manifest_id="workout.delete_exercise", module="workout", description="Delete an exercise-directory entry by exact UUID. By default this refuses when plans or workout logs reference it. Set delete_references true only when the user explicitly agrees to remove those plan items and historical log items too.", params_schema={"type":"object","properties":{"exercise_id":{"type":"string"},"delete_references":{"type":"boolean"}},"required":["exercise_id"]})
def remove_workout_exercise(exercise_id: str, delete_references: bool=False): return delete_exercise(exercise_id, force=delete_references)


@register_function(manifest_id="workout.delete_session", module="workout", description="Permanently delete one workout session by its exact UUID. Read workout history first to identify the intended session; never guess an ID or delete a different session.", params_schema={"type":"object","properties":{"session_id":{"type":"string","description":"Exact workout session UUID returned by workout.get_history"}},"required":["session_id"]})
def remove_workout_session(session_id: str):
    return delete_session(session_id)


@register_function(manifest_id="workout.get_progress", module="workout", description="Get workout consistency, streaks, active goal progress, time series, and optional per-exercise load/volume trends.", params_schema={"type":"object","properties":{"days":{"type":"integer","minimum":7,"maximum":730},"exercise":{"type":"string"}}})
def get_progress(days: int=90, exercise: str=""):
    return dashboard(days=days,exercise=exercise or None)


@register_function(manifest_id="workout.set_goal", module="workout", description="Create a consistency or progress goal for weekly sessions, weekly minutes, or an exercise target weight.", params_schema={"type":"object","properties":{"title":{"type":"string"},"metric":{"type":"string","enum":["sessions_per_week","minutes_per_week","exercise_weight_kg"]},"target_value":{"type":"number"},"unit":{"type":"string"},"exercise":{"type":"string"},"start_date":{"type":"string"},"end_date":{"type":"string"},"metadata":{"type":"object"}},"required":["title","metric","target_value"]})
def set_goal(title: str, metric: str, target_value: float, unit: str="", exercise: str="", start_date: str="", end_date: str="", metadata: dict|None=None):
    from django.utils.dateparse import parse_date
    if metric not in dict(WorkoutGoal.METRIC_CHOICES): raise ValueError("Unsupported workout goal metric")
    target=None
    if exercise: target,_=resolve_exercise(exercise)
    item=WorkoutGoal.objects.create(title=title,metric=metric,target_value=target_value,unit=unit,exercise=target,start_date=parse_date(start_date) if start_date else None,end_date=parse_date(end_date) if end_date else None,metadata=metadata or {})
    return goal_payload(item)


@register_function(manifest_id="workout.list_goals", module="workout", description="List workout goals and exact IDs before editing or deleting one.", params_schema={"type":"object","properties":{"active_only":{"type":"boolean"}}})
def list_workout_goals(active_only: bool=False): return {"goals":list_goal_records(active_only=active_only)}


@register_function(manifest_id="workout.update_goal", module="workout", description="Edit or archive a workout goal by exact UUID after listing goals.", params_schema={"type":"object","properties":{"goal_id":{"type":"string"},"title":{"type":"string"},"metric":{"type":"string","enum":["sessions_per_week","minutes_per_week","exercise_weight_kg"]},"target_value":{"type":"number"},"unit":{"type":"string"},"exercise":{"type":"string"},"start_date":{"type":"string"},"end_date":{"type":"string"},"active":{"type":"boolean"},"metadata":{"type":"object"}},"required":["goal_id"]})
def edit_workout_goal(goal_id: str, **changes): return update_goal_record(goal_id,**changes)


@register_function(manifest_id="workout.delete_goal", module="workout", description="Delete a workout goal by exact UUID after listing goals. Use active false instead when the user asks to archive it.", params_schema={"type":"object","properties":{"goal_id":{"type":"string"}},"required":["goal_id"]})
def remove_workout_goal(goal_id: str): return delete_goal_record(goal_id)
