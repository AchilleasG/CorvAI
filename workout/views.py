import base64
import httpx
from uuid import UUID
from CorvAI import settings as corv_settings
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from ninja import Router
from ninja.errors import HttpError

from workout.models import Exercise, WorkoutGoal, WorkoutPlan
from workout.schemas import ExerciseIn, ExerciseUpdateIn, FinishSessionIn, GoalIn, PlanIn, PlanUpdateIn, SessionActionIn, SessionIn, SessionItemUpdateIn, SetLogUpdateIn, StartSessionIn, WorkoutSessionUpdateIn, WorkoutSpeechIn
from workout.services import active_sessions, dashboard, delete_exercise, delete_plan, delete_session, enrich_exercise, exercise_payload, finish_session, goal_payload, history, log_session, normalize_exercise_name, plan_payload, resolve_exercise, save_plan, set_session_status, start_session, update_session_item, update_set_log

router=Router(tags=["Workout"])

@router.post("/guidance/speech")
def workout_speech(request, payload: WorkoutSpeechIn):
    text = " ".join(payload.text.split()).strip()[:600]
    if not text: raise HttpError(400, "Speech text is required")
    if not corv_settings.openai_key: raise HttpError(503, "Cloud voice is not configured")
    try:
        response = httpx.post("https://api.openai.com/v1/audio/speech", headers={"Authorization":f"Bearer {corv_settings.openai_key}"}, json={"model":"gpt-4o-mini-tts","voice":"alloy","input":text,"response_format":"mp3"}, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as exc: raise HttpError(502, f"Cloud voice failed: {exc}")
    return {"content_type":"audio/mpeg","audio_base64":base64.b64encode(response.content).decode("ascii")}

@router.get("/exercises")
def list_exercises(request, query: str=""):
    qs=Exercise.objects.all()
    if query: qs=qs.filter(name__icontains=query)
    return {"exercises":[exercise_payload(x) for x in qs[:500]]}

@router.post("/exercises")
def create_exercise(request, payload: ExerciseIn):
    item, created=resolve_exercise(payload.name,defaults=payload.dict())
    return {**exercise_payload(item),"created":created}

@router.get("/exercises/{exercise_id}/details")
def get_exercise_details(request, exercise_id: UUID, refresh: bool=False):
    try: return enrich_exercise(exercise_id, force=refresh)
    except ValueError as exc: raise HttpError(404, str(exc))

@router.patch("/exercises/{exercise_id}")
def edit_exercise(request, exercise_id: UUID, payload: ExerciseUpdateIn):
    item=get_object_or_404(Exercise,id=exercise_id)
    changes=payload.dict(exclude_none=True)
    if "name" in changes:
        clean=" ".join(changes["name"].split()).strip()
        if not clean: raise HttpError(400,"Exercise name is required")
        normalized=normalize_exercise_name(clean)
        if Exercise.objects.exclude(id=item.id).filter(normalized_name=normalized).exists(): raise HttpError(409,"An exercise with that name already exists")
        changes["name"],changes["normalized_name"]=clean,normalized
    for key,value in changes.items(): setattr(item,key,value)
    item.save(); return exercise_payload(item)

@router.delete("/exercises/{exercise_id}")
def remove_exercise(request, exercise_id: UUID, force: bool=False):
    try: return delete_exercise(exercise_id, force=force)
    except ValueError as exc: raise HttpError(409 if "used by" in str(exc) else 404, str(exc))

@router.get("/plans")
def list_plans(request): return {"plans":[plan_payload(x) for x in WorkoutPlan.objects.prefetch_related("plan_exercises__exercise").all()]}

@router.get("/plans/{plan_id}")
def get_plan(request, plan_id: UUID): return plan_payload(get_object_or_404(WorkoutPlan,id=plan_id))

@router.patch("/plans/{plan_id}")
def edit_plan(request, plan_id: UUID, payload: PlanUpdateIn):
    item=get_object_or_404(WorkoutPlan,id=plan_id); changes=payload.dict(exclude_none=True)
    if "title" in changes and not changes["title"].strip(): raise HttpError(400,"Plan title is required")
    for key,value in changes.items(): setattr(item,key,value)
    item.save(); return plan_payload(item)

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

@router.patch("/sessions/{session_id}/details")
def edit_session(request, session_id: UUID, payload: WorkoutSessionUpdateIn):
    from workout.models import WorkoutSession
    from workout.services import _parse_dt, session_payload
    item=get_object_or_404(WorkoutSession,id=session_id); changes=payload.dict(exclude_none=True)
    if "started_at" in changes: changes["started_at"]=_parse_dt(changes["started_at"])
    if "ended_at" in changes: changes["ended_at"]=_parse_dt(changes["ended_at"])
    for key,value in changes.items(): setattr(item,key,value)
    item.save(); return session_payload(item)

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

@router.patch("/sessions/sets/{set_id}")
def change_session_set(request, set_id: UUID, payload: SetLogUpdateIn):
    try: return update_set_log(set_id, **payload.dict())
    except ValueError as exc: raise HttpError(400, str(exc))

@router.post("/sessions/{session_id}/finish")
def complete_session(request, session_id: UUID, payload: FinishSessionIn):
    try: return finish_session(session_id, **payload.dict())
    except ValueError as exc: raise HttpError(400,str(exc))

@router.post("/sessions/{session_id}/state")
def change_session_state(request, session_id: UUID, payload: SessionActionIn):
    try: return set_session_status(session_id, payload.action)
    except ValueError as exc: raise HttpError(400, str(exc))

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
