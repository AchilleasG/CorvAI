from ninja import Schema
from typing import Any, Optional


class ExerciseSpecIn(Schema):
    name: str
    sets: Optional[int]=None
    reps: Optional[Any]=None
    weight_kg: Optional[float]=None
    duration_seconds: Optional[int]=None
    distance_km: Optional[float]=None
    rest_seconds: Optional[int]=None
    rpe: Optional[float]=None
    notes: str=""
    category: str=""
    muscle_group: str=""
    equipment: str=""
    aliases: list[str]=[]
    metadata: dict={}


class ExerciseIn(Schema):
    name: str
    aliases: list[str]=[]
    category: str=""
    muscle_group: str=""
    equipment: str=""
    instructions: str=""
    metadata: dict={}


class PlanIn(Schema):
    title: str
    description: str=""
    goal: str=""
    source: str="manual"
    schedule: dict={}
    exercises: list[ExerciseSpecIn]
    metadata: dict={}


class SessionIn(Schema):
    title: str=""
    plan: Optional[str]=None
    started_at: Optional[str]=None
    ended_at: Optional[str]=None
    notes: str=""
    exercises: list[ExerciseSpecIn]
    metadata: dict={}


class GoalIn(Schema):
    title: str
    metric: str="sessions_per_week"
    target_value: float
    unit: str=""
    exercise: Optional[str]=None
    start_date: Optional[str]=None
    end_date: Optional[str]=None
    active: bool=True
    metadata: dict={}


class StartSessionIn(Schema):
    title: str=""
    plan: Optional[str]=None
    started_at: Optional[str]=None
    notes: str=""
    exercises: list[ExerciseSpecIn]=[]
    metadata: dict={}


class SessionItemUpdateIn(Schema):
    completed: Optional[bool]=None
    sets: Optional[int]=None
    reps: Optional[int]=None
    weight_kg: Optional[float]=None
    duration_seconds: Optional[int]=None
    distance_km: Optional[float]=None
    rpe: Optional[float]=None
    notes: Optional[str]=None
    metadata: Optional[dict]=None


class FinishSessionIn(Schema):
    ended_at: Optional[str]=None
    notes: Optional[str]=None
