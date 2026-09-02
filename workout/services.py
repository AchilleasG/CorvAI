from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from workout.models import Exercise, WorkoutExerciseLog, WorkoutGoal, WorkoutPlan, WorkoutPlanExercise, WorkoutSession


def normalize_exercise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def exercise_payload(item: Exercise) -> dict:
    return {"id": str(item.id), "name": item.name, "aliases": item.aliases, "category": item.category, "muscle_group": item.muscle_group, "equipment": item.equipment, "instructions": item.instructions, "metadata": item.metadata}


def resolve_exercise(name: str, *, defaults: dict | None = None) -> tuple[Exercise, bool]:
    clean = " ".join(str(name or "").split()).strip()
    if not clean: raise ValueError("Exercise name is required")
    normalized = normalize_exercise_name(clean)
    item = Exercise.objects.filter(Q(normalized_name=normalized) | Q(name__iexact=clean)).first()
    if not item:
        for candidate in Exercise.objects.exclude(aliases=[]):
            if normalized in {normalize_exercise_name(alias) for alias in (candidate.aliases or [])}:
                item = candidate; break
    if item: return item, False
    data = defaults or {}
    return Exercise.objects.create(name=clean, normalized_name=normalized, aliases=data.get("aliases") or [], category=data.get("category") or "", muscle_group=data.get("muscle_group") or "", equipment=data.get("equipment") or "", instructions=data.get("instructions") or "", metadata=data.get("metadata") or {}), True


def _exercise_spec_payload(row) -> dict:
    return {"id": str(row.id), "exercise": exercise_payload(row.exercise), "order_index": row.order_index, "sets": row.sets, "reps": row.reps, "weight_kg": row.weight_kg, "duration_seconds": row.duration_seconds, "distance_km": row.distance_km, "rest_seconds": row.rest_seconds, "notes": row.notes, "metadata": row.metadata}


def plan_payload(plan: WorkoutPlan, *, detailed=True) -> dict:
    data = {"id": str(plan.id), "title": plan.title, "description": plan.description, "goal": plan.goal, "source": plan.source, "schedule": plan.schedule, "active": plan.active, "metadata": plan.metadata, "created_at": plan.created_at.isoformat(), "updated_at": plan.updated_at.isoformat()}
    if detailed: data["exercises"] = [_exercise_spec_payload(row) for row in plan.plan_exercises.select_related("exercise").all()]
    return data


@transaction.atomic
def save_plan(*, title: str, exercises: list[dict], description="", goal="", schedule=None, source="manual", metadata=None) -> dict:
    if not str(title).strip(): raise ValueError("Plan title is required")
    if not exercises: raise ValueError("At least one exercise is required")
    plan = WorkoutPlan.objects.create(title=str(title).strip(), description=description or "", goal=goal or "", schedule=schedule or {}, source=source if source in {"manual", "import", "corv"} else "manual", metadata=metadata or {})
    created=[]
    for index, spec in enumerate(exercises):
        exercise, was_created = resolve_exercise(spec.get("name") or spec.get("exercise") or "", defaults=spec)
        created.append(exercise.name) if was_created else None
        WorkoutPlanExercise.objects.create(plan=plan, exercise=exercise, order_index=index, sets=spec.get("sets"), reps=str(spec.get("reps") or ""), weight_kg=spec.get("weight_kg"), duration_seconds=spec.get("duration_seconds"), distance_km=spec.get("distance_km"), rest_seconds=spec.get("rest_seconds"), notes=spec.get("notes") or "", metadata=spec.get("metadata") or {})
    data=plan_payload(plan); data["created_exercises"]=created; return data


def _parse_dt(value, fallback=None):
    if isinstance(value, datetime): result=value
    else: result=parse_datetime(str(value)) if value else fallback
    if result and timezone.is_naive(result): result=timezone.make_aware(result)
    return result


def _find_plan(value):
    if not value: return None
    text=str(value).strip(); query=Q(title__iexact=text)
    try: query |= Q(pk=UUID(text))
    except (ValueError, TypeError): pass
    return WorkoutPlan.objects.filter(query).first()


def _logged_reps(value):
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Logged reps must be a whole number") from exc
    if result < 0:
        raise ValueError("Logged reps cannot be negative")
    return result


def log_payload(row: WorkoutExerciseLog) -> dict:
    return {"id": str(row.id), "exercise": exercise_payload(row.exercise), "order_index": row.order_index, "sets": row.sets, "reps": row.reps, "weight_kg": row.weight_kg, "duration_seconds": row.duration_seconds, "distance_km": row.distance_km, "rpe": row.rpe, "notes": row.notes, "metadata": row.metadata, "completed": row.completed, "completed_at": row.completed_at.isoformat() if row.completed_at else None}


def session_payload(session: WorkoutSession) -> dict:
    duration = int((session.ended_at-session.started_at).total_seconds()) if session.ended_at else sum((x.duration_seconds or 0) for x in session.exercise_logs.all())
    return {"id": str(session.id), "plan_id": str(session.plan_id) if session.plan_id else None, "plan_title": session.plan.title if session.plan_id else None, "title": session.title, "status": session.status, "started_at": session.started_at.isoformat(), "ended_at": session.ended_at.isoformat() if session.ended_at else None, "duration_seconds": duration, "notes": session.notes, "metadata": session.metadata, "exercises": [log_payload(row) for row in session.exercise_logs.select_related("exercise").all()]}


@transaction.atomic
def log_session(*, exercises: list[dict], started_at=None, ended_at=None, plan=None, title="", notes="", metadata=None) -> dict:
    if not exercises: raise ValueError("At least one logged exercise is required")
    start=_parse_dt(started_at, timezone.now()); end=_parse_dt(ended_at)
    if end and end < start: raise ValueError("Workout end time cannot be before start time")
    target_plan=_find_plan(plan)
    if plan and not target_plan: raise ValueError(f"Workout plan '{plan}' was not found")
    session=WorkoutSession.objects.create(plan=target_plan, started_at=start, ended_at=end, title=title or (target_plan.title if target_plan else "Workout"), notes=notes or "", metadata=metadata or {})
    created=[]
    for index, spec in enumerate(exercises):
        exercise, was_created=resolve_exercise(spec.get("name") or spec.get("exercise") or "", defaults=spec)
        created.append(exercise.name) if was_created else None
        WorkoutExerciseLog.objects.create(session=session, exercise=exercise, order_index=index, sets=spec.get("sets"), reps=_logged_reps(spec.get("reps")), weight_kg=spec.get("weight_kg"), duration_seconds=spec.get("duration_seconds"), distance_km=spec.get("distance_km"), rpe=spec.get("rpe"), notes=spec.get("notes") or "", metadata=spec.get("metadata") or {})
    data=session_payload(session); data["created_exercises"]=created; return data


def _plan_specs(plan: WorkoutPlan) -> list[dict]:
    specs = []
    for row in plan.plan_exercises.select_related("exercise").all():
        metadata = dict(row.metadata or {})
        reps = row.reps or None
        if reps is not None:
            try: reps = int(reps)
            except (TypeError, ValueError): metadata["prescribed_reps"] = reps; reps = None
        specs.append({"name": row.exercise.name, "sets": row.sets, "reps": reps, "weight_kg": row.weight_kg, "duration_seconds": row.duration_seconds, "distance_km": row.distance_km, "notes": row.notes, "metadata": metadata})
    return specs


@transaction.atomic
def start_session(*, plan=None, exercises=None, title="", started_at=None, notes="", metadata=None) -> dict:
    target_plan = _find_plan(plan)
    if plan and not target_plan:
        raise ValueError(f"Workout plan '{plan}' was not found")
    specs = list(exercises or (_plan_specs(target_plan) if target_plan else []))
    if not specs:
        raise ValueError("Choose a plan or provide at least one exercise")
    session = WorkoutSession.objects.create(plan=target_plan, status=WorkoutSession.STATUS_ACTIVE, started_at=_parse_dt(started_at, timezone.now()), title=title or (target_plan.title if target_plan else "Workout"), notes=notes or "", metadata=metadata or {})
    created = []
    for index, spec in enumerate(specs):
        exercise, was_created = resolve_exercise(spec.get("name") or spec.get("exercise") or "", defaults=spec)
        if was_created: created.append(exercise.name)
        WorkoutExerciseLog.objects.create(session=session, exercise=exercise, order_index=index, sets=spec.get("sets"), reps=_logged_reps(spec.get("reps")), weight_kg=spec.get("weight_kg"), duration_seconds=spec.get("duration_seconds"), distance_km=spec.get("distance_km"), rpe=spec.get("rpe"), notes=spec.get("notes") or "", metadata=spec.get("metadata") or {}, completed=False)
    data = session_payload(session); data["created_exercises"] = created; return data


def active_sessions() -> list[dict]:
    qs = WorkoutSession.objects.filter(status=WorkoutSession.STATUS_ACTIVE).select_related("plan").prefetch_related("exercise_logs__exercise")
    return [session_payload(item) for item in qs]


@transaction.atomic
def update_session_item(log_id, *, completed=None, sets=None, reps=None, weight_kg=None, duration_seconds=None, distance_km=None, rpe=None, notes=None, metadata=None) -> dict:
    try: row = WorkoutExerciseLog.objects.select_related("session", "exercise").get(pk=log_id)
    except (WorkoutExerciseLog.DoesNotExist, ValueError, TypeError): raise ValueError("Workout checklist item was not found")
    if row.session.status != WorkoutSession.STATUS_ACTIVE: raise ValueError("Only an active workout can be updated")
    values = {"sets": sets, "weight_kg": weight_kg, "duration_seconds": duration_seconds, "distance_km": distance_km, "rpe": rpe, "notes": notes}
    for field, value in values.items():
        if value is not None: setattr(row, field, value)
    if reps is not None: row.reps = _logged_reps(reps)
    if metadata is not None: row.metadata = {**(row.metadata or {}), **metadata}
    if completed is not None:
        row.completed = bool(completed); row.completed_at = timezone.now() if row.completed else None
    row.save()
    return log_payload(row)


@transaction.atomic
def finish_session(session_id, *, ended_at=None, notes=None) -> dict:
    try: session = WorkoutSession.objects.select_related("plan").prefetch_related("exercise_logs__exercise").get(pk=session_id)
    except (WorkoutSession.DoesNotExist, ValueError, TypeError): raise ValueError("Workout session was not found")
    if session.status != WorkoutSession.STATUS_ACTIVE: raise ValueError("Workout session is already completed")
    session.status = WorkoutSession.STATUS_COMPLETED
    session.ended_at = _parse_dt(ended_at, timezone.now())
    if notes is not None: session.notes = notes
    session.save(update_fields=["status", "ended_at", "notes", "updated_at"])
    return session_payload(session)


@transaction.atomic
def delete_plan(plan_id) -> dict:
    try: plan = WorkoutPlan.objects.prefetch_related("plan_exercises__exercise").get(pk=plan_id)
    except (WorkoutPlan.DoesNotExist, ValueError, TypeError): raise ValueError("Workout plan was not found")
    deleted = plan_payload(plan)
    preserved_sessions = plan.sessions.count()
    plan.delete()
    return {"deleted": True, "plan": deleted, "preserved_sessions": preserved_sessions}


@transaction.atomic
def delete_exercise(exercise_id, *, force=False) -> dict:
    try: exercise = Exercise.objects.get(pk=exercise_id)
    except (Exercise.DoesNotExist, ValueError, TypeError): raise ValueError("Exercise was not found")
    plan_entries = exercise.plan_entries.count(); log_entries = exercise.logs.count()
    if (plan_entries or log_entries) and not force:
        raise ValueError(f"Exercise is used by {plan_entries} plan entries and {log_entries} workout logs; explicitly allow reference deletion to remove it")
    deleted = exercise_payload(exercise)
    if force:
        exercise.plan_entries.all().delete(); exercise.logs.all().delete()
    exercise.delete()
    return {"deleted": True, "exercise": deleted, "deleted_plan_entries": plan_entries, "deleted_log_entries": log_entries}


def delete_session(session_id) -> dict:
    try:
        session = WorkoutSession.objects.select_related("plan").prefetch_related("exercise_logs__exercise").get(pk=session_id)
    except (WorkoutSession.DoesNotExist, ValueError, TypeError):
        raise ValueError("Workout session was not found")
    deleted = session_payload(session)
    session.delete()
    return {"deleted": True, "session": deleted}


def history(*, start_date=None, end_date=None, exercise=None, limit=100) -> list[dict]:
    qs=WorkoutSession.objects.select_related("plan").prefetch_related("exercise_logs__exercise")
    start=parse_date(str(start_date)) if start_date else None; end=parse_date(str(end_date)) if end_date else None
    if start: qs=qs.filter(started_at__date__gte=start)
    if end: qs=qs.filter(started_at__date__lte=end)
    if exercise:
        normalized=normalize_exercise_name(exercise); qs=qs.filter(Q(exercise_logs__exercise__normalized_name=normalized)|Q(exercise_logs__exercise__name__iexact=exercise)).distinct()
    return [session_payload(item) for item in qs[:max(1,min(int(limit),500))]]


def goal_payload(goal: WorkoutGoal, current_value=0) -> dict:
    return {"id": str(goal.id), "title": goal.title, "metric": goal.metric, "target_value": goal.target_value, "unit": goal.unit, "exercise_id": str(goal.exercise_id) if goal.exercise_id else None, "exercise_name": goal.exercise.name if goal.exercise_id else None, "start_date": goal.start_date.isoformat() if goal.start_date else None, "end_date": goal.end_date.isoformat() if goal.end_date else None, "active": goal.active, "metadata": goal.metadata, "current_value": round(float(current_value),2), "progress_percent": min(100,round(float(current_value)/goal.target_value*100,1)) if goal.target_value else 0}


def dashboard(*, days=90, exercise=None) -> dict:
    days=max(7,min(int(days),730)); today=timezone.localdate(); start=today-timedelta(days=days-1)
    sessions=list(WorkoutSession.objects.filter(started_at__date__gte=start).prefetch_related("exercise_logs__exercise").order_by("started_at"))
    by_day=defaultdict(lambda:{"sessions":0,"duration_minutes":0.0,"volume_kg":0.0})
    trained=set(); exercise_points=[]; normalized=normalize_exercise_name(exercise) if exercise else ""
    for session in sessions:
        day=timezone.localtime(session.started_at).date(); trained.add(day); by_day[day]["sessions"]+=1
        seconds=int((session.ended_at-session.started_at).total_seconds()) if session.ended_at else 0
        for row in session.exercise_logs.all():
            seconds += (row.duration_seconds or 0) if not session.ended_at else 0
            volume=(row.weight_kg or 0)*(row.reps or 0)*(row.sets or 1); by_day[day]["volume_kg"]+=volume
            if not normalized or row.exercise.normalized_name==normalized:
                if row.weight_kg is not None or volume:
                    exercise_points.append({"date":day.isoformat(),"exercise":row.exercise.name,"weight_kg":row.weight_kg,"volume_kg":round(volume,2),"reps":row.reps,"sets":row.sets})
        by_day[day]["duration_minutes"] += seconds/60
    daily=[]
    for offset in range(days):
        day=start+timedelta(days=offset); values=by_day[day]; daily.append({"date":day.isoformat(),"sessions":values["sessions"],"duration_minutes":round(values["duration_minutes"],1),"volume_kg":round(values["volume_kg"],2)})
    week_start=today-timedelta(days=today.weekday()); weekly=[]
    for back in range(11,-1,-1):
        ws=week_start-timedelta(weeks=back); we=ws+timedelta(days=6); chunk=[s for s in sessions if ws<=timezone.localtime(s.started_at).date()<=we]; weekly.append({"week_start":ws.isoformat(),"sessions":len(chunk)})
    streak=0; cursor=today
    if cursor not in trained: cursor-=timedelta(days=1)
    while cursor in trained: streak+=1; cursor-=timedelta(days=1)
    current_week_sessions=sum(1 for s in sessions if timezone.localtime(s.started_at).date()>=week_start)
    current_week_minutes=sum(x["duration_minutes"] for x in daily if date.fromisoformat(x["date"])>=week_start)
    goals=[]
    for goal in WorkoutGoal.objects.filter(active=True).select_related("exercise"):
        if goal.metric==WorkoutGoal.METRIC_SESSIONS: value=current_week_sessions
        elif goal.metric==WorkoutGoal.METRIC_MINUTES: value=current_week_minutes
        else:
            relevant=[p.get("weight_kg") or 0 for p in exercise_points if not goal.exercise_id or p["exercise"]==goal.exercise.name]; value=max(relevant,default=0)
        goals.append(goal_payload(goal,value))
    return {"days":days,"session_count":len(sessions),"current_streak_days":streak,"trained_days":len(trained),"current_week_sessions":current_week_sessions,"daily":daily,"weekly":weekly,"exercise_trend":exercise_points,"goals":goals}
