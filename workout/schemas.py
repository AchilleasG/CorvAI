from ninja import Schema
from typing import Any, Optional


class ExerciseSpecIn(Schema):
    name: str
    sets: Optional[int]=None
    reps: Optional[Any]=None
    reps_min: Optional[int]=None
    reps_max: Optional[int]=None
    weight_kg: Optional[float]=None
    duration_seconds: Optional[int]=None
    duration_seconds_min: Optional[int]=None
    duration_seconds_max: Optional[int]=None
    distance_km: Optional[float]=None
    rest_seconds: Optional[int]=None
    rpe: Optional[float]=None
    notes: str=""
    category: str=""
    muscle_group: str=""
    equipment: str=""
    aliases: list[str]=[]
    metadata: dict={}
    phase_type: str="reps"
    set_targets: list[dict]=[]
    block_key: str=""
    block_name: str=""
    cycle_count: int=1
    per_side: bool=False


class PlannedSessionIn(Schema):
    name: str
    description: str=""
    guidance_mode: str="checklist"
    guidance_level: str="minimal"
    auto_start_phases: bool=False
    settings: dict={}
    exercises: list[ExerciseSpecIn]


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
    exercises: list[ExerciseSpecIn]=[]
    sessions: list[PlannedSessionIn]=[]
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
    planned_session: Optional[str]=None
    started_at: Optional[str]=None
    notes: str=""
    exercises: list[ExerciseSpecIn]=[]
    metadata: dict={}
    mode: str="checklist"
    guidance_level: str="minimal"


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
    draft: bool=False


class SetLogUpdateIn(Schema):
    status: Optional[str]=None
    actual: Optional[dict]=None
    notes: Optional[str]=None


class SessionActionIn(Schema):
    action: str


class WorkoutSpeechIn(Schema):
    text: str


class ExerciseUpdateIn(Schema):
    name: Optional[str]=None
    aliases: Optional[list[str]]=None
    category: Optional[str]=None
    muscle_group: Optional[str]=None
    equipment: Optional[str]=None
    instructions: Optional[str]=None
    metadata: Optional[dict]=None


class PlanUpdateIn(Schema):
    title: Optional[str]=None
    description: Optional[str]=None
    goal: Optional[str]=None
    active: Optional[bool]=None
    schedule: Optional[dict]=None
    metadata: Optional[dict]=None


class WorkoutSessionUpdateIn(Schema):
    title: Optional[str]=None
    notes: Optional[str]=None
    started_at: Optional[str]=None
    ended_at: Optional[str]=None
    metadata: Optional[dict]=None
