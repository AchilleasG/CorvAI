from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from collections import defaultdict
from datetime import date, datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
import httpx
from PIL import Image

from workout.models import Exercise, WorkoutExerciseLog, WorkoutGoal, WorkoutPlan, WorkoutPlanExercise, WorkoutPlanSession, WorkoutSession, WorkoutSetLog


def normalize_exercise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def exercise_payload(item: Exercise) -> dict:
    return {"id": str(item.id), "name": item.name, "aliases": item.aliases, "category": item.category, "muscle_group": item.muscle_group, "equipment": item.equipment, "instructions": item.instructions, "metadata": item.metadata, "external_provider": item.external_provider, "external_id": item.external_id, "enrichment_data": item.enrichment_data, "demo_media_url": item.demo_media_url, "enriched_at": item.enriched_at.isoformat() if item.enriched_at else None, "enrichment_error": item.enrichment_error}


EXERCISE_CATALOG_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
EXERCISE_IMAGE_BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
_catalog_cache = None


def _catalog(client):
    global _catalog_cache
    if _catalog_cache is None:
        response = client.get(EXERCISE_CATALOG_URL)
        response.raise_for_status()
        _catalog_cache = response.json()
    return _catalog_cache


def _match_catalog_exercise(name: str, catalog: list[dict]) -> dict | None:
    wanted = normalize_exercise_name(name)
    # Only use exact canonical names or reviewed aliases. Exercise names are
    # semantic: spelling similarity can turn a dead hang into a dead bug or a
    # push-up into a plyometric push-up, which is worse than returning no demo.
    catalog_aliases = {
        "pull up": "pullups", "pull ups": "pullups",
        "push up": "pushups", "push ups": "pushups",
        "single arm dumbbell bench press": "one arm dumbbell bench press",
        "standing dumbbell overhead press": "standing dumbbell press",
    }
    target = catalog_aliases.get(wanted, wanted)
    for candidate in catalog:
        candidate_name = normalize_exercise_name(candidate.get("name", ""))
        if target == candidate_name:
            return candidate
    return None


def _build_demo_gif(exercise: Exercise, image_paths: list[str], client) -> str:
    frames = []
    for image_path in image_paths[:4]:
        safe_path = "/".join(quote(part, safe="") for part in str(image_path).split("/") if part not in {"", ".", ".."})
        response = client.get(f"{EXERCISE_IMAGE_BASE}{safe_path}")
        response.raise_for_status()
        with Image.open(BytesIO(response.content)) as image:
            frames.append(image.convert("RGB").copy())
    if not frames:
        return ""
    relative = Path("workout") / "exercise-demos" / f"{exercise.id}.gif"
    target = Path(settings.MEDIA_ROOT) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(target, format="GIF", save_all=True, append_images=frames[1:], duration=900, loop=0, optimize=True)
    return f"{settings.MEDIA_URL.rstrip('/')}/{relative.as_posix()}"


def enrich_exercise(exercise_id, *, force=False, client=None) -> dict:
    """Lazy, persistent enrichment from a public-domain exercise catalog."""
    try:
        exercise = Exercise.objects.get(pk=exercise_id)
    except (Exercise.DoesNotExist, ValueError, TypeError):
        raise ValueError("Exercise was not found")
    if exercise.enriched_at and exercise.enrichment_data and not force:
        return exercise_payload(exercise)
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": "CorvAI workout enrichment"})
    try:
        match = _match_catalog_exercise(exercise.name, _catalog(client))
        if not match:
            # A previous version accepted loose fuzzy matches. On an explicit
            # refresh, remove that provider-owned stale content so the UI never
            # keeps presenting a different movement as authoritative.
            if force and exercise.external_provider == "free-exercise-db":
                overrides = set((exercise.metadata or {}).get("enrichment_overrides") or [])
                for field in ("instructions", "category", "muscle_group", "equipment"):
                    if field not in overrides:
                        setattr(exercise, field, "")
                exercise.external_provider = ""
                exercise.external_id = ""
                exercise.enrichment_data = {}
                exercise.demo_media_url = ""
                exercise.enriched_at = None
            exercise.enrichment_error = "No sufficiently close exercise was found in the enrichment catalog."
            exercise.save()
            return exercise_payload(exercise)
        data = {
            "force": match.get("force"), "level": match.get("level"), "mechanic": match.get("mechanic"),
            "primary_muscles": match.get("primaryMuscles") or [], "secondary_muscles": match.get("secondaryMuscles") or [],
            "instructions": match.get("instructions") or [], "category": match.get("category") or "",
            "equipment": match.get("equipment") or "", "source_name": match.get("name") or "",
            "source_url": "https://github.com/yuhonas/free-exercise-db", "license": "Unlicense / public domain",
            "match_method": "reviewed_alias" if normalize_exercise_name(exercise.name) != normalize_exercise_name(match.get("name", "")) else "exact",
            "managed_fields": ["instructions", "category", "muscle_group", "equipment"],
        }
        demo_url = _build_demo_gif(exercise, match.get("images") or [], client)
        exercise.external_provider = "free-exercise-db"
        exercise.external_id = str(match.get("id") or "")
        exercise.enrichment_data = data
        exercise.demo_media_url = demo_url
        exercise.enriched_at = timezone.now()
        exercise.enrichment_error = ""
        overrides = set((exercise.metadata or {}).get("enrichment_overrides") or [])
        if "instructions" not in overrides and data["instructions"]:
            exercise.instructions = "\n".join(f"{index}. {step}" for index, step in enumerate(data["instructions"], 1))
        if "category" not in overrides:
            exercise.category = data["category"]
        if "muscle_group" not in overrides:
            exercise.muscle_group = ", ".join(data["primary_muscles"])
        if "equipment" not in overrides:
            exercise.equipment = data["equipment"]
        exercise.save()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        exercise.enrichment_error = f"Exercise enrichment is temporarily unavailable: {exc}"
        exercise.save(update_fields=["enrichment_error", "updated_at"])
    finally:
        if owns_client:
            client.close()
    return exercise_payload(exercise)


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


@transaction.atomic
def update_exercise(exercise_id, **changes) -> dict:
    try: item=Exercise.objects.get(pk=exercise_id)
    except (Exercise.DoesNotExist, ValueError, TypeError): raise ValueError("Exercise was not found")
    allowed={"name","aliases","category","muscle_group","equipment","instructions","metadata"}
    values={key:value for key,value in changes.items() if key in allowed and value is not None}
    if "name" in values:
        clean=" ".join(str(values["name"]).split()).strip()
        if not clean: raise ValueError("Exercise name is required")
        normalized=normalize_exercise_name(clean)
        if Exercise.objects.exclude(pk=item.pk).filter(normalized_name=normalized).exists(): raise ValueError("An exercise with that name already exists")
        values["name"],values["normalized_name"]=clean,normalized
    managed = {"instructions", "category", "muscle_group", "equipment"}
    edited_managed = managed.intersection(values)
    if edited_managed:
        metadata = dict(values.get("metadata", item.metadata) or {})
        metadata["enrichment_overrides"] = sorted(set(metadata.get("enrichment_overrides") or []).union(edited_managed))
        values["metadata"] = metadata
    for key,value in values.items(): setattr(item,key,value)
    item.save(); return exercise_payload(item)


def enrichment_issues() -> list[dict]:
    """Return entries needing human/LLM research without inventing a match."""
    issues = []
    for item in Exercise.objects.all().order_by("name"):
        missing = [field for field in ("instructions", "muscle_group", "equipment", "demo_media_url") if not getattr(item, field)]
        if item.enrichment_error or missing:
            issues.append({"id": str(item.id), "name": item.name, "missing": missing, "error": item.enrichment_error})
    return issues


def _exercise_spec_payload(row) -> dict:
    return {"id": str(row.id), "exercise": exercise_payload(row.exercise), "order_index": row.order_index, "sets": row.sets, "reps": row.reps, "weight_kg": row.weight_kg, "duration_seconds": row.duration_seconds, "distance_km": row.distance_km, "rest_seconds": row.rest_seconds, "notes": row.notes, "metadata": row.metadata, "phase_type": row.phase_type, "set_targets": row.set_targets, "block_key": row.block_key, "block_name": row.block_name, "cycle_count": row.cycle_count}


def _planned_session_payload(item: WorkoutPlanSession) -> dict:
    return {"id": str(item.id), "name": item.name, "order_index": item.order_index, "description": item.description, "guidance_mode": item.guidance_mode, "guidance_level": item.guidance_level, "auto_start_phases": item.auto_start_phases, "settings": item.settings, "exercises": [_exercise_spec_payload(row) for row in item.exercises.select_related("exercise").all()]}


def _prepare_prescription(raw: dict) -> dict:
    """Preserve planner-friendly ranges in the existing prescription model."""
    spec = dict(raw)
    metadata = dict(spec.get("metadata") or {})
    reps_min, reps_max = spec.get("reps_min"), spec.get("reps_max")
    if spec.get("reps") in (None, "") and (reps_min is not None or reps_max is not None):
        low, high = reps_min if reps_min is not None else reps_max, reps_max if reps_max is not None else reps_min
        spec["reps"] = str(low) if low == high else f"{low}-{high}"
    if reps_min is not None: metadata["reps_min"] = reps_min
    if reps_max is not None: metadata["reps_max"] = reps_max
    duration_min, duration_max = spec.get("duration_seconds_min"), spec.get("duration_seconds_max")
    if spec.get("duration_seconds") is None and (duration_min is not None or duration_max is not None):
        spec["duration_seconds"] = duration_max if duration_max is not None else duration_min
    if duration_min is not None: metadata["duration_seconds_min"] = duration_min
    if duration_max is not None: metadata["duration_seconds_max"] = duration_max
    if duration_min is not None or duration_max is not None: spec["phase_type"] = "timed"
    if spec.get("per_side"): metadata["per_side"] = True
    spec["metadata"] = metadata
    return spec


def plan_payload(plan: WorkoutPlan, *, detailed=True) -> dict:
    data = {"id": str(plan.id), "title": plan.title, "description": plan.description, "goal": plan.goal, "source": plan.source, "schedule": plan.schedule, "active": plan.active, "metadata": plan.metadata, "created_at": plan.created_at.isoformat(), "updated_at": plan.updated_at.isoformat()}
    if detailed:
        data["exercises"] = [_exercise_spec_payload(row) for row in plan.plan_exercises.select_related("exercise").filter(planned_session__isnull=True)]
        data["sessions"] = [_planned_session_payload(item) for item in plan.planned_sessions.prefetch_related("exercises__exercise").all()]
    return data


@transaction.atomic
def _create_plan_exercises(plan, exercises, created, planned_session=None):
    for index, raw_spec in enumerate(exercises):
        spec = _prepare_prescription(raw_spec)
        exercise, was_created = resolve_exercise(spec.get("name") or spec.get("exercise") or "", defaults=spec)
        if was_created: created.append(exercise.name)
        WorkoutPlanExercise.objects.create(plan=plan, planned_session=planned_session, exercise=exercise, order_index=index, sets=spec.get("sets"), reps=str(spec.get("reps") or ""), weight_kg=spec.get("weight_kg"), duration_seconds=spec.get("duration_seconds"), distance_km=spec.get("distance_km"), rest_seconds=spec.get("rest_seconds"), notes=spec.get("notes") or "", metadata=spec.get("metadata") or {}, phase_type=spec.get("phase_type") or ("timed" if spec.get("duration_seconds") else "reps"), set_targets=spec.get("set_targets") or [], block_key=spec.get("block_key") or "", block_name=spec.get("block_name") or "", cycle_count=max(1, int(spec.get("cycle_count") or 1)))


@transaction.atomic
def save_plan(*, title: str, exercises: list[dict] | None = None, sessions: list[dict] | None = None, description="", goal="", schedule=None, source="manual", metadata=None) -> dict:
    if not str(title).strip(): raise ValueError("Plan title is required")
    if not exercises and not sessions: raise ValueError("At least one planned session or exercise is required")
    plan = WorkoutPlan.objects.create(title=str(title).strip(), description=description or "", goal=goal or "", schedule=schedule or {}, source=source if source in {"manual", "import", "corv"} else "manual", metadata=metadata or {})
    created=[]
    _create_plan_exercises(plan, exercises or [], created)
    for index, spec in enumerate(sessions or []):
        item = WorkoutPlanSession.objects.create(plan=plan, name=str(spec.get("name") or f"Session {index + 1}").strip(), order_index=index, description=spec.get("description") or "", guidance_mode=spec.get("guidance_mode") or "checklist", guidance_level=spec.get("guidance_level") or "minimal", auto_start_phases=bool(spec.get("auto_start_phases", False)), settings=spec.get("settings") or {})
        _create_plan_exercises(plan, spec.get("exercises") or [], created, item)
    data=plan_payload(plan); data["created_exercises"]=created; return data


@transaction.atomic
def update_plan(plan_id, *, title=None, description=None, goal=None, schedule=None, active=None, metadata=None, exercises=None, sessions=None) -> dict:
    try: plan=WorkoutPlan.objects.get(pk=plan_id)
    except (WorkoutPlan.DoesNotExist, ValueError, TypeError): raise ValueError("Workout plan was not found")
    for key,value in {"title":title,"description":description,"goal":goal,"schedule":schedule,"active":active,"metadata":metadata}.items():
        if value is not None: setattr(plan,key,value)
    if not plan.title.strip(): raise ValueError("Plan title is required")
    plan.save()
    created=[]
    if exercises is not None or sessions is not None:
        plan.plan_exercises.all().delete(); plan.planned_sessions.all().delete()
        _create_plan_exercises(plan, exercises or [], created)
        for index,spec in enumerate(sessions or []):
            item=WorkoutPlanSession.objects.create(plan=plan,name=str(spec.get("name") or f"Session {index+1}").strip(),order_index=index,description=spec.get("description") or "",guidance_mode=spec.get("guidance_mode") or "checklist",guidance_level=spec.get("guidance_level") or "minimal",auto_start_phases=bool(spec.get("auto_start_phases",False)),settings=spec.get("settings") or {})
            _create_plan_exercises(plan,spec.get("exercises") or [],created,item)
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
    return {"id": str(row.id), "exercise": exercise_payload(row.exercise), "order_index": row.order_index, "sets": row.sets, "reps": row.reps, "weight_kg": row.weight_kg, "duration_seconds": row.duration_seconds, "distance_km": row.distance_km, "rpe": row.rpe, "notes": row.notes, "metadata": row.metadata, "completed": row.completed, "completed_at": row.completed_at.isoformat() if row.completed_at else None, "phase_type": row.phase_type, "set_targets": row.set_targets, "block_key": row.block_key, "block_name": row.block_name, "cycle_index": row.cycle_index, "set_logs": [{"id": str(item.id), "set_index": item.set_index, "target": item.target, "actual": item.actual, "status": item.status, "started_at": item.started_at.isoformat() if item.started_at else None, "completed_at": item.completed_at.isoformat() if item.completed_at else None, "notes": item.notes} for item in row.set_logs.all()]}


def session_payload(session: WorkoutSession) -> dict:
    duration = int((session.ended_at-session.started_at).total_seconds()) if session.ended_at else sum((x.duration_seconds or 0) for x in session.exercise_logs.all())
    return {"id": str(session.id), "plan_id": str(session.plan_id) if session.plan_id else None, "plan_title": session.plan.title if session.plan_id else None, "planned_session_id": str(session.planned_session_id) if session.planned_session_id else None, "planned_session_name": session.planned_session.name if session.planned_session_id else None, "title": session.title, "status": session.status, "mode": session.mode, "guidance_level": session.guidance_level, "started_at": session.started_at.isoformat(), "ended_at": session.ended_at.isoformat() if session.ended_at else None, "paused_at": session.paused_at.isoformat() if session.paused_at else None, "accumulated_pause_seconds": session.accumulated_pause_seconds, "duration_seconds": duration, "notes": session.notes, "metadata": session.metadata, "exercises": [log_payload(row) for row in session.exercise_logs.select_related("exercise").prefetch_related("set_logs").all()]}


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


def _plan_specs(plan: WorkoutPlan, planned_session=None) -> list[dict]:
    specs = []
    rows = plan.plan_exercises.select_related("exercise")
    rows = rows.filter(planned_session=planned_session) if planned_session else rows.filter(planned_session__isnull=True)
    for row in rows:
        metadata = dict(row.metadata or {})
        reps = row.reps or None
        if reps is not None:
            try: reps = int(reps)
            except (TypeError, ValueError): metadata["prescribed_reps"] = reps; reps = None
        specs.append({"name": row.exercise.name, "sets": row.sets, "reps": reps, "weight_kg": row.weight_kg, "duration_seconds": row.duration_seconds, "distance_km": row.distance_km, "rest_seconds": row.rest_seconds, "notes": row.notes, "metadata": metadata, "phase_type": row.phase_type, "set_targets": row.set_targets, "block_key": row.block_key, "block_name": row.block_name, "cycle_count": row.cycle_count})
    return specs


@transaction.atomic
def start_session(*, plan=None, planned_session=None, exercises=None, title="", started_at=None, notes="", mode="checklist", guidance_level="minimal", metadata=None) -> dict:
    target_plan = _find_plan(plan)
    if plan and not target_plan:
        raise ValueError(f"Workout plan '{plan}' was not found")
    target_planned_session = None
    if planned_session:
        try: target_planned_session = WorkoutPlanSession.objects.get(pk=planned_session, plan=target_plan)
        except (WorkoutPlanSession.DoesNotExist, ValueError, TypeError): raise ValueError("Planned workout session was not found")
    elif target_plan and target_plan.planned_sessions.exists():
        target_planned_session = target_plan.planned_sessions.first()
    specs = list(exercises or (_plan_specs(target_plan, target_planned_session) if target_plan else []))
    if not specs:
        raise ValueError("Choose a plan or provide at least one exercise")
    selected_mode = mode or (target_planned_session.guidance_mode if target_planned_session else "checklist")
    selected_guidance = guidance_level or (target_planned_session.guidance_level if target_planned_session else "minimal")
    session = WorkoutSession.objects.create(plan=target_plan, planned_session=target_planned_session, status=WorkoutSession.STATUS_ACTIVE, started_at=_parse_dt(started_at, timezone.now()), title=title or (target_planned_session.name if target_planned_session else target_plan.title if target_plan else "Workout"), notes=notes or "", mode=selected_mode, guidance_level=selected_guidance, metadata=metadata or {})
    created = []
    expanded = []
    for spec in specs:
        for cycle_index in range(1, max(1, int(spec.get("cycle_count") or 1)) + 1): expanded.append((spec, cycle_index))
    for index, (spec, cycle_index) in enumerate(expanded):
        exercise, was_created = resolve_exercise(spec.get("name") or spec.get("exercise") or "", defaults=spec)
        if was_created: created.append(exercise.name)
        row = WorkoutExerciseLog.objects.create(session=session, exercise=exercise, order_index=index, sets=spec.get("sets"), reps=_logged_reps(spec.get("reps")), weight_kg=spec.get("weight_kg"), duration_seconds=spec.get("duration_seconds"), distance_km=spec.get("distance_km"), rpe=spec.get("rpe"), notes=spec.get("notes") or "", metadata={**(spec.get("metadata") or {}), "rest_seconds": spec.get("rest_seconds")}, completed=False, phase_type=spec.get("phase_type") or ("timed" if spec.get("duration_seconds") else "reps"), set_targets=spec.get("set_targets") or [], block_key=spec.get("block_key") or "", block_name=spec.get("block_name") or "", cycle_index=cycle_index)
        targets = spec.get("set_targets") or []
        count = max(1, int(spec.get("sets") or len(targets) or 1))
        for set_index in range(1, count + 1):
            target = dict(targets[set_index - 1]) if set_index <= len(targets) else {key: value for key, value in {"reps": spec.get("reps"), "weight_kg": spec.get("weight_kg"), "duration_seconds": spec.get("duration_seconds"), "distance_km": spec.get("distance_km"), "rest_seconds": spec.get("rest_seconds")}.items() if value is not None}
            prescribed = spec.get("metadata") or {}
            if "reps" not in target and prescribed.get("prescribed_reps"): target["reps"] = prescribed["prescribed_reps"]
            for field in ("duration_seconds_min", "duration_seconds_max", "per_side"):
                if prescribed.get(field) is not None: target[field] = prescribed[field]
            WorkoutSetLog.objects.create(exercise_log=row, set_index=set_index, target=target)
    data = session_payload(session); data["created_exercises"] = created; return data


def active_sessions() -> list[dict]:
    qs = WorkoutSession.objects.filter(status__in=[WorkoutSession.STATUS_ACTIVE, WorkoutSession.STATUS_PAUSED, WorkoutSession.STATUS_DRAFT]).select_related("plan", "planned_session").prefetch_related("exercise_logs__exercise", "exercise_logs__set_logs")
    return [session_payload(item) for item in qs]


@transaction.atomic
def update_session_item(log_id, *, completed=None, sets=None, reps=None, weight_kg=None, duration_seconds=None, distance_km=None, rpe=None, notes=None, metadata=None) -> dict:
    try: row = WorkoutExerciseLog.objects.select_related("session", "exercise").get(pk=log_id)
    except (WorkoutExerciseLog.DoesNotExist, ValueError, TypeError): raise ValueError("Workout checklist item was not found")
    if row.session.status not in {WorkoutSession.STATUS_ACTIVE, WorkoutSession.STATUS_PAUSED, WorkoutSession.STATUS_DRAFT}: raise ValueError("Only an in-progress workout can be updated")
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
def finish_session(session_id, *, ended_at=None, notes=None, draft=False) -> dict:
    try: session = WorkoutSession.objects.select_related("plan").prefetch_related("exercise_logs__exercise").get(pk=session_id)
    except (WorkoutSession.DoesNotExist, ValueError, TypeError): raise ValueError("Workout session was not found")
    if session.status not in {WorkoutSession.STATUS_ACTIVE, WorkoutSession.STATUS_PAUSED}: raise ValueError("Workout session is already awaiting submission or completed")
    session.status = WorkoutSession.STATUS_DRAFT if draft else WorkoutSession.STATUS_COMPLETED
    session.ended_at = _parse_dt(ended_at, timezone.now())
    if notes is not None: session.notes = notes
    session.save(update_fields=["status", "ended_at", "notes", "updated_at"])
    return session_payload(session)


@transaction.atomic
def set_session_status(session_id, action: str) -> dict:
    try: session = WorkoutSession.objects.select_related("plan", "planned_session").prefetch_related("exercise_logs__exercise", "exercise_logs__set_logs").get(pk=session_id)
    except (WorkoutSession.DoesNotExist, ValueError, TypeError): raise ValueError("Workout session was not found")
    now = timezone.now()
    if action == "pause" and session.status == WorkoutSession.STATUS_ACTIVE:
        session.status, session.paused_at = WorkoutSession.STATUS_PAUSED, now
    elif action == "resume" and session.status == WorkoutSession.STATUS_PAUSED:
        if session.paused_at: session.accumulated_pause_seconds += max(0, int((now - session.paused_at).total_seconds()))
        session.status, session.paused_at = WorkoutSession.STATUS_ACTIVE, None
    elif action == "submit" and session.status == WorkoutSession.STATUS_DRAFT:
        session.status, session.ended_at = WorkoutSession.STATUS_COMPLETED, session.ended_at or now
    elif action == "abandon" and session.status in {WorkoutSession.STATUS_ACTIVE, WorkoutSession.STATUS_PAUSED, WorkoutSession.STATUS_DRAFT}:
        session.status, session.ended_at = WorkoutSession.STATUS_ABANDONED, now
    else: raise ValueError(f"Cannot {action} a {session.status} workout")
    session.save()
    return session_payload(session)


@transaction.atomic
def update_set_log(set_id, *, status=None, actual=None, notes=None) -> dict:
    try: item = WorkoutSetLog.objects.select_related("exercise_log__session").get(pk=set_id)
    except (WorkoutSetLog.DoesNotExist, ValueError, TypeError): raise ValueError("Workout set was not found")
    if item.exercise_log.session.status not in {WorkoutSession.STATUS_ACTIVE, WorkoutSession.STATUS_PAUSED, WorkoutSession.STATUS_DRAFT}: raise ValueError("Workout is no longer editable")
    now = timezone.now()
    if status:
        item.status = status
        if status == "active" and not item.started_at: item.started_at = now
        if status in {"completed", "skipped"}: item.completed_at = now
    if actual is not None: item.actual = actual
    if notes is not None: item.notes = notes
    item.save()
    row = item.exercise_log
    row.completed = not row.set_logs.exclude(status__in=["completed", "skipped"]).exists()
    row.completed_at = now if row.completed else None
    row.save(update_fields=["completed", "completed_at"])
    return log_payload(row)


@transaction.atomic
def edit_session(session_id, *, title=None, notes=None, started_at=None, ended_at=None, metadata=None) -> dict:
    try: item=WorkoutSession.objects.select_related("plan","planned_session").prefetch_related("exercise_logs__exercise","exercise_logs__set_logs").get(pk=session_id)
    except (WorkoutSession.DoesNotExist, ValueError, TypeError): raise ValueError("Workout session was not found")
    for key,value in {"title":title,"notes":notes,"metadata":metadata}.items():
        if value is not None: setattr(item,key,value)
    if started_at is not None: item.started_at=_parse_dt(started_at)
    if ended_at is not None: item.ended_at=_parse_dt(ended_at)
    if item.ended_at and item.ended_at < item.started_at: raise ValueError("Workout end time cannot be before start time")
    item.save(); return session_payload(item)


@transaction.atomic
def edit_exercise_log(log_id, *, exercise=None, sets=None, reps=None, weight_kg=None, duration_seconds=None, distance_km=None, rpe=None, notes=None, metadata=None) -> dict:
    try: row=WorkoutExerciseLog.objects.select_related("exercise").prefetch_related("set_logs").get(pk=log_id)
    except (WorkoutExerciseLog.DoesNotExist, ValueError, TypeError): raise ValueError("Workout exercise log was not found")
    if exercise:
        target,_=resolve_exercise(exercise); row.exercise=target
    for key,value in {"sets":sets,"weight_kg":weight_kg,"duration_seconds":duration_seconds,"distance_km":distance_km,"rpe":rpe,"notes":notes,"metadata":metadata}.items():
        if value is not None: setattr(row,key,value)
    if reps is not None: row.reps=_logged_reps(reps)
    row.save(); return log_payload(row)


@transaction.atomic
def edit_any_set_log(set_id, *, status=None, actual=None, target=None, notes=None) -> dict:
    try: item=WorkoutSetLog.objects.select_related("exercise_log__exercise").get(pk=set_id)
    except (WorkoutSetLog.DoesNotExist, ValueError, TypeError): raise ValueError("Workout set was not found")
    if status is not None: item.status=status
    if actual is not None: item.actual=actual
    if target is not None: item.target=target
    if notes is not None: item.notes=notes
    item.save(); return log_payload(item.exercise_log)


def list_goals(*, active_only=False) -> list[dict]:
    qs=WorkoutGoal.objects.select_related("exercise"); qs=qs.filter(active=True) if active_only else qs
    return [goal_payload(item) for item in qs]


@transaction.atomic
def update_goal_record(goal_id, *, title=None, metric=None, target_value=None, unit=None, exercise=None, start_date=None, end_date=None, active=None, metadata=None) -> dict:
    try: item=WorkoutGoal.objects.select_related("exercise").get(pk=goal_id)
    except (WorkoutGoal.DoesNotExist, ValueError, TypeError): raise ValueError("Workout goal was not found")
    if metric is not None:
        if metric not in dict(WorkoutGoal.METRIC_CHOICES): raise ValueError("Unsupported workout goal metric")
        item.metric=metric
    for key,value in {"title":title,"target_value":target_value,"unit":unit,"active":active,"metadata":metadata}.items():
        if value is not None: setattr(item,key,value)
    if exercise is not None: item.exercise=resolve_exercise(exercise)[0] if exercise else None
    if start_date is not None: item.start_date=parse_date(start_date) if start_date else None
    if end_date is not None: item.end_date=parse_date(end_date) if end_date else None
    item.save(); return goal_payload(item)


def delete_goal_record(goal_id) -> dict:
    try: item=WorkoutGoal.objects.select_related("exercise").get(pk=goal_id)
    except (WorkoutGoal.DoesNotExist, ValueError, TypeError): raise ValueError("Workout goal was not found")
    payload=goal_payload(item); item.delete(); return {"deleted":True,"goal":payload}


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
