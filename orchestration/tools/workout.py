from __future__ import annotations

from django.db.models import Q

from orchestration.registry import register_function
from workout.models import Exercise, WorkoutGoal, WorkoutPlan
from workout.services import active_sessions, dashboard, delete_exercise, delete_plan, delete_session, exercise_payload, finish_session, goal_payload, history, log_session, plan_payload, resolve_exercise, save_plan, start_session, update_session_item


EXERCISE_ITEM = {
    "type": "object",
    "properties": {
        "name": {"type": "string"}, "sets": {"type": "integer"}, "reps": {"type": ["integer", "string"]},
        "weight_kg": {"type": "number"}, "duration_seconds": {"type": "integer"}, "distance_km": {"type": "number"},
        "rest_seconds": {"type": "integer"}, "rpe": {"type": "number"}, "notes": {"type": "string"},
        "category": {"type": "string"}, "muscle_group": {"type": "string"}, "equipment": {"type": "string"},
        "metadata": {"type": "object"},
    },
    "required": ["name"],
}


@register_function(manifest_id="workout.list_exercises", module="workout", description="Inspect the exercise directory so you can semantically match the user's wording to the best existing canonical exercise. Search broadly or list all entries before logging; do not create a near-duplicate.", params_schema={"type":"object","properties":{"query":{"type":"string"}}})
def list_exercises(query: str=""):
    qs=Exercise.objects.all()
    if query: qs=qs.filter(Q(name__icontains=query)|Q(category__icontains=query)|Q(muscle_group__icontains=query))
    return {"exercises":[exercise_payload(item) for item in qs[:100]]}


@register_function(manifest_id="workout.save_plan", module="workout", description="Create a new workout plan or import an existing structured plan. Exercise names resolve to the directory and missing exercises are created.", params_schema={"type":"object","properties":{"title":{"type":"string"},"description":{"type":"string"},"goal":{"type":"string"},"source":{"type":"string","enum":["corv","import","manual"]},"schedule":{"type":"object"},"exercises":{"type":"array","items":EXERCISE_ITEM},"metadata":{"type":"object"}},"required":["title","exercises"]})
def save_workout_plan(title: str, exercises: list[dict], description: str="", goal: str="", source: str="corv", schedule: dict|None=None, metadata: dict|None=None):
    return save_plan(title=title,exercises=exercises,description=description,goal=goal,source=source,schedule=schedule or {},metadata=metadata or {})


@register_function(manifest_id="workout.list_plans", module="workout", description="List saved workout plans with their exercise prescriptions.", params_schema={"type":"object","properties":{"active_only":{"type":"boolean"}}})
def list_plans(active_only: bool=False):
    qs=WorkoutPlan.objects.prefetch_related("plan_exercises__exercise"); qs=qs.filter(active=True) if active_only else qs
    return {"plans":[plan_payload(item) for item in qs[:100]]}


@register_function(manifest_id="workout.log_session", module="workout", description="Log a completed or ongoing workout session after you have inspected the exercise directory and used your judgment to map each mentioned movement to an existing canonical exercise name. Only pass a new name when no existing entry is semantically appropriate; the logger then creates it. Include date/time and optional sets, reps, kilos, duration, distance, RPE, notes, and arbitrary metadata.", params_schema={"type":"object","properties":{"title":{"type":"string"},"plan":{"type":"string"},"started_at":{"type":"string","description":"ISO datetime; defaults to now"},"ended_at":{"type":"string"},"notes":{"type":"string"},"exercises":{"type":"array","items":EXERCISE_ITEM},"metadata":{"type":"object"}},"required":["exercises"]})
def log_workout_session(exercises: list[dict], started_at: str="", ended_at: str="", plan: str="", title: str="", notes: str="", metadata: dict|None=None):
    return log_session(exercises=exercises,started_at=started_at or None,ended_at=ended_at or None,plan=plan or None,title=title,notes=notes,metadata=metadata or {})


@register_function(manifest_id="workout.get_history", module="workout", description="Read logged workout history, optionally filtered by dates or exercise.", params_schema={"type":"object","properties":{"start_date":{"type":"string"},"end_date":{"type":"string"},"exercise":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":500}}})
def get_history(start_date: str="", end_date: str="", exercise: str="", limit: int=100):
    return {"sessions":history(start_date=start_date or None,end_date=end_date or None,exercise=exercise or None,limit=limit)}


@register_function(manifest_id="workout.start_session", module="workout", description="Start an in-progress workout from a saved plan or exercise list. This creates a visible checklist; inspect the exercise directory first for ad-hoc exercises.", params_schema={"type":"object","properties":{"plan":{"type":"string"},"title":{"type":"string"},"started_at":{"type":"string"},"notes":{"type":"string"},"exercises":{"type":"array","items":EXERCISE_ITEM},"metadata":{"type":"object"}}})
def begin_workout_session(plan: str="", exercises: list[dict]|None=None, title: str="", started_at: str="", notes: str="", metadata: dict|None=None):
    return start_session(plan=plan or None, exercises=exercises or [], title=title, started_at=started_at or None, notes=notes, metadata=metadata or {})


@register_function(manifest_id="workout.get_active_sessions", module="workout", description="View all in-progress workout sessions and their exercise checklist completion state.", params_schema={"type":"object","properties":{}})
def get_active_workout_sessions(): return {"sessions": active_sessions()}


@register_function(manifest_id="workout.update_session_item", module="workout", description="Check or uncheck an exercise in an active workout and optionally record actual sets, reps, kilos, duration, distance, RPE, notes, or metadata.", params_schema={"type":"object","properties":{"log_id":{"type":"string"},"completed":{"type":"boolean"},"sets":{"type":"integer"},"reps":{"type":"integer"},"weight_kg":{"type":"number"},"duration_seconds":{"type":"integer"},"distance_km":{"type":"number"},"rpe":{"type":"number"},"notes":{"type":"string"},"metadata":{"type":"object"}},"required":["log_id"]})
def change_workout_item(log_id: str, completed=None, sets=None, reps=None, weight_kg=None, duration_seconds=None, distance_km=None, rpe=None, notes=None, metadata=None):
    return update_session_item(log_id, completed=completed, sets=sets, reps=reps, weight_kg=weight_kg, duration_seconds=duration_seconds, distance_km=distance_km, rpe=rpe, notes=notes, metadata=metadata)


@register_function(manifest_id="workout.finish_session", module="workout", description="Finish an active workout session, preserving checked items and recorded actual performance.", params_schema={"type":"object","properties":{"session_id":{"type":"string"},"ended_at":{"type":"string"},"notes":{"type":"string"}},"required":["session_id"]})
def complete_workout_session(session_id: str, ended_at: str="", notes=None): return finish_session(session_id, ended_at=ended_at or None, notes=notes)


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
