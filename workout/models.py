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


class WorkoutPlanExercise(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(WorkoutPlan, on_delete=models.CASCADE, related_name="plan_exercises")
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

    class Meta:
        ordering = ["order_index", "exercise__name"]
        constraints = [models.UniqueConstraint(fields=["plan", "exercise", "order_index"], name="workout_unique_plan_exercise_order")]


class WorkoutSession(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [(STATUS_ACTIVE, "Active"), (STATUS_COMPLETED, "Completed")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(WorkoutPlan, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_COMPLETED, db_index=True)
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    title = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta: ordering = ["order_index", "created_at"]


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
