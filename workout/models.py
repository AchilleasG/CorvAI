from __future__ import annotations

import uuid
from django.db import models


class Exercise(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    normalized_name = models.CharField(max_length=160, unique=True)
    aliases = models.JSONField(default=list, blank=True)
    category = models.CharField(max_length=80, blank=True, default="")
    muscle_group = models.CharField(max_length=120, blank=True, default="")
    equipment = models.CharField(max_length=120, blank=True, default="")
    instructions = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    external_provider = models.CharField(max_length=80, blank=True, default="")
    external_id = models.CharField(max_length=200, blank=True, default="")
    enrichment_data = models.JSONField(default=dict, blank=True)
    demo_media_url = models.TextField(blank=True, default="")
    enriched_at = models.DateTimeField(null=True, blank=True)
    enrichment_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self): return self.name


class WorkoutPlan(models.Model):
    SOURCE_CORV = "corv"
    SOURCE_IMPORT = "import"
    SOURCE_MANUAL = "manual"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    goal = models.TextField(blank=True, default="")
    source = models.CharField(max_length=24, default=SOURCE_MANUAL)
    schedule = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta: ordering = ["-active", "-updated_at"]

    def __str__(self): return self.title


class WorkoutPlanSession(models.Model):
    """A named day/session inside a reusable workout plan."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(WorkoutPlan, on_delete=models.CASCADE, related_name="planned_sessions")
    name = models.CharField(max_length=200)
    order_index = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True, default="")
    guidance_mode = models.CharField(max_length=24, default="checklist")
    auto_start_phases = models.BooleanField(default=False)
    guidance_level = models.CharField(max_length=24, default="minimal")
    settings = models.JSONField(default=dict, blank=True)

    class Meta: ordering = ["order_index", "name"]


class WorkoutPlanExercise(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(WorkoutPlan, on_delete=models.CASCADE, related_name="plan_exercises")
    planned_session = models.ForeignKey(WorkoutPlanSession, null=True, blank=True, on_delete=models.CASCADE, related_name="exercises")
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name="plan_entries")
    order_index = models.PositiveIntegerField(default=0)
    sets = models.PositiveIntegerField(null=True, blank=True)
    reps = models.CharField(max_length=64, blank=True, default="")
    weight_kg = models.FloatField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    distance_km = models.FloatField(null=True, blank=True)
    rest_seconds = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    phase_type = models.CharField(max_length=20, default="reps")
    set_targets = models.JSONField(default=list, blank=True)
    block_key = models.CharField(max_length=80, blank=True, default="")
    block_name = models.CharField(max_length=160, blank=True, default="")
    cycle_count = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order_index", "exercise__name"]
        constraints = [
            # Each named session owns its own sequence: the same movement may
            # validly occupy the same position in separate sessions.
            models.UniqueConstraint(
                fields=["planned_session", "order_index"],
                condition=models.Q(planned_session__isnull=False),
                name="workout_unique_session_exercise_order",
            ),
            # Keep legacy plan-level prescriptions independent of named sessions.
            models.UniqueConstraint(
                fields=["plan", "order_index"],
                condition=models.Q(planned_session__isnull=True),
                name="workout_unique_plan_level_exercise_order",
            ),
        ]


class WorkoutSession(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_PAUSED = "paused"
    STATUS_DRAFT = "draft"
    STATUS_ABANDONED = "abandoned"
    STATUS_CHOICES = [(STATUS_ACTIVE, "Active"), (STATUS_PAUSED, "Paused"), (STATUS_DRAFT, "Draft report"), (STATUS_COMPLETED, "Completed"), (STATUS_ABANDONED, "Abandoned")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(WorkoutPlan, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions")
    planned_session = models.ForeignKey(WorkoutPlanSession, null=True, blank=True, on_delete=models.SET_NULL, related_name="workout_sessions")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_COMPLETED, db_index=True)
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    title = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    mode = models.CharField(max_length=24, default="checklist")
    guidance_level = models.CharField(max_length=24, default="minimal")
    paused_at = models.DateTimeField(null=True, blank=True)
    accumulated_pause_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta: ordering = ["-started_at"]

    def __str__(self): return self.title or f"Workout {self.started_at:%Y-%m-%d}"


class WorkoutExerciseLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(WorkoutSession, on_delete=models.CASCADE, related_name="exercise_logs")
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name="logs")
    order_index = models.PositiveIntegerField(default=0)
    sets = models.PositiveIntegerField(null=True, blank=True)
    reps = models.PositiveIntegerField(null=True, blank=True)
    weight_kg = models.FloatField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    distance_km = models.FloatField(null=True, blank=True)
    rpe = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    completed = models.BooleanField(default=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    phase_type = models.CharField(max_length=20, default="reps")
    set_targets = models.JSONField(default=list, blank=True)
    block_key = models.CharField(max_length=80, blank=True, default="")
    block_name = models.CharField(max_length=160, blank=True, default="")
    cycle_index = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta: ordering = ["order_index", "created_at"]


class WorkoutSetLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exercise_log = models.ForeignKey(WorkoutExerciseLog, on_delete=models.CASCADE, related_name="set_logs")
    set_index = models.PositiveIntegerField(default=1)
    target = models.JSONField(default=dict, blank=True)
    actual = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, default="pending")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["set_index"]
        constraints = [models.UniqueConstraint(fields=["exercise_log", "set_index"], name="workout_unique_exercise_set")]


class WorkoutGoal(models.Model):
    METRIC_SESSIONS = "sessions_per_week"
    METRIC_MINUTES = "minutes_per_week"
    METRIC_WEIGHT = "exercise_weight_kg"
    METRIC_CHOICES = [(METRIC_SESSIONS, "Sessions per week"), (METRIC_MINUTES, "Minutes per week"), (METRIC_WEIGHT, "Exercise weight")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    metric = models.CharField(max_length=40, choices=METRIC_CHOICES, default=METRIC_SESSIONS)
    target_value = models.FloatField()
    unit = models.CharField(max_length=32, blank=True, default="")
    exercise = models.ForeignKey(Exercise, null=True, blank=True, on_delete=models.SET_NULL, related_name="goals")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta: ordering = ["-active", "-created_at"]
