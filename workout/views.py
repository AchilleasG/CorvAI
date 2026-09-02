from uuid import UUID
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from ninja import Router
from ninja.errors import HttpError

from workout.models import Exercise, WorkoutGoal, WorkoutPlan
from workout.schemas import ExerciseIn, FinishSessionIn, GoalIn, PlanIn, SessionIn, SessionItemUpdateIn, StartSessionIn
from workout.services import active_sessions, dashboard, delete_exercise, delete_plan, delete_session, exercise_payload, finish_session, goal_payload, history, log_session, normalize_exercise_name, plan_payload, resolve_exercise, save_plan, start_session, update_session_item

router=Router(tags=["Workout"])

@router.get("/exercises")
def list_exercises(request, query: str=""):
    qs=Exercise.objects.all()
    if query: qs=qs.filter(name__icontains=query)
    return {"exercises":[exercise_payload(x) for x in qs[:500]]}

@router.post("/exercises")
def create_exercise(request, payload: ExerciseIn):
    item, created=resolve_exercise(payload.name,defaults=payload.dict())
    return {**exercise_payload(item),"created":created}

@router.delete("/exercises/{exercise_id}")
def remove_exercise(request, exercise_id: UUID, force: bool=False):
    try: return delete_exercise(exercise_id, force=force)
    except ValueError as exc: raise HttpError(409 if "used by" in str(exc) else 404, str(exc))

@router.get("/plans")
def list_plans(request): return {"plans":[plan_payload(x) for x in WorkoutPlan.objects.prefetch_related("plan_exercises__exercise").all()]}

@router.get("/plans/{plan_id}")
def get_plan(request, plan_id: UUID): return plan_payload(get_object_or_404(WorkoutPlan,id=plan_id))

@router.delete("/plans/{plan_id}")
def remove_plan(request, plan_id: UUID):
    try: return delete_plan(plan_id)
    except ValueError as exc: raise HttpError(404,str(exc))

@router.post("/plans")
def create_plan(request, payload: PlanIn):
    try: return save_plan(**payload.dict())
    except ValueError as exc: raise HttpError(400,str(exc))

@router.get("/sessions")
def list_sessions(request, start_date: str="", end_date: str="", exercise: str="", limit: int=100):
    return {"sessions":history(start_date=start_date or None,end_date=end_date or None,exercise=exercise or None,limit=limit)}

@router.post("/sessions")
def create_session(request, payload: SessionIn):
    try: return log_session(**payload.dict())
    except ValueError as exc: raise HttpError(400,str(exc))

@router.get("/sessions/active")
def get_active_sessions(request): return {"sessions": active_sessions()}

@router.post("/sessions/start")
def begin_session(request, payload: StartSessionIn):
    try: return start_session(**payload.dict())
    except ValueError as exc: raise HttpError(400,str(exc))

@router.patch("/sessions/items/{log_id}")
def change_session_item(request, log_id: UUID, payload: SessionItemUpdateIn):
    try: return update_session_item(log_id, **payload.dict())
    except ValueError as exc: raise HttpError(400,str(exc))

@router.post("/sessions/{session_id}/finish")
def complete_session(request, session_id: UUID, payload: FinishSessionIn):
    try: return finish_session(session_id, **payload.dict())
    except ValueError as exc: raise HttpError(400,str(exc))

@router.delete("/sessions/{session_id}")
def remove_session(request, session_id: UUID):
    try: return delete_session(session_id)
    except ValueError as exc: raise HttpError(404,str(exc))

@router.get("/goals")
def list_goals(request): return {"goals":[goal_payload(x) for x in WorkoutGoal.objects.select_related("exercise").all()]}

@router.post("/goals")
def create_goal(request, payload: GoalIn):
    exercise=None
    if payload.exercise: exercise,_=resolve_exercise(payload.exercise)
    if payload.metric not in dict(WorkoutGoal.METRIC_CHOICES): raise HttpError(400,"Unsupported workout goal metric")
    item=WorkoutGoal.objects.create(title=payload.title,metric=payload.metric,target_value=payload.target_value,unit=payload.unit,exercise=exercise,start_date=parse_date(payload.start_date) if payload.start_date else None,end_date=parse_date(payload.end_date) if payload.end_date else None,active=payload.active,metadata=payload.metadata)
    return goal_payload(item)

@router.patch("/goals/{goal_id}")
def update_goal(request, goal_id: UUID, active: bool):
    item=get_object_or_404(WorkoutGoal,id=goal_id); item.active=active; item.save(update_fields=["active","updated_at"]); return goal_payload(item)

@router.get("/dashboard")
def get_dashboard(request, days: int=90, exercise: str=""): return dashboard(days=days,exercise=exercise or None)
