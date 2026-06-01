from __future__ import annotations

import uuid
from django.db import models
from django.contrib.postgres.fields import ArrayField
from pgvector.django import VectorField

from chat.models import Chat


class ToolModule(models.Model):
    """
    A high-level grouping of functions (e.g., calendar, files).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    secrets_encrypted = models.TextField(blank=True, default="", help_text="Encrypted secrets blob")
    caller_instructions = models.TextField(
        blank=True,
        default="",
        help_text="Hints for the Function Caller when planning tool use.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return self.slug


class ToolFunction(models.Model):
    """
    Manifest describing a callable function exposed to the Function Caller.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manifest_id = models.CharField(max_length=255, unique=True)
    module = models.ForeignKey(
        ToolModule, on_delete=models.CASCADE, related_name="functions"
    )
    name = models.CharField(max_length=255)
    description = models.TextField()
    params_schema = models.JSONField(default=dict, blank=True)
    return_schema = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)
    deprecated = models.BooleanField(default=False)
    handler_ref = models.CharField(
        max_length=255,
        help_text="Python dotted path or registry key resolved by the Function Runner.",
    )
    embedding = models.JSONField(
        default=None,
        null=True,
        blank=True,
        help_text="Optional vector representation for retrieval.",
    )
    examples = models.JSONField(
        default=list,
        blank=True,
        help_text="List of example {user_prompt, params} objects for better matching.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["manifest_id"]
        indexes = [
            models.Index(fields=["manifest_id"]),
            models.Index(fields=["module", "deprecated"]),
        ]

    def __str__(self):
        return self.manifest_id


class Job(models.Model):
    """
    Durable job/process that spans Function Caller and Runner steps.
    """

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_WAITING_USER = "waiting_on_user"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_WAITING_USER, "Waiting on User"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELED, "Canceled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(
        Chat, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs"
    )
    session_id = models.CharField(
        max_length=255, blank=True, default="", help_text="UI session/window identifier."
    )
    trace_id = models.CharField(
        max_length=255, blank=True, default="", help_text="Correlation id across layers."
    )
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    progress = models.FloatField(default=0.0)
    user_visible_summary = models.TextField(blank=True, default="")
    internal_notes = models.TextField(blank=True, default="")
    cancel_requested = models.BooleanField(default=False)
    error_summary = models.TextField(blank=True, default="")
    module = models.ForeignKey(
        ToolModule, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs"
    )
    active_function = models.ForeignKey(
        ToolFunction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_jobs",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["session_id"]),
            models.Index(fields=["trace_id"]),
        ]

    def __str__(self):
        return f"Job {self.id} [{self.status}]"


class JobEvent(models.Model):
    """
    Append-only event stream for a job; used for resumability and multi-session visibility.
    """

    EVENT_INFO = "info"
    EVENT_PROGRESS = "progress"
    EVENT_ERROR = "error"
    EVENT_STATE = "state_change"

    VISIBILITY_USER = "user_visible"
    VISIBILITY_TOOL = "tool_only"
    VISIBILITY_SYSTEM = "system_note"

    EVENT_CHOICES = [
        (EVENT_INFO, "Info"),
        (EVENT_PROGRESS, "Progress"),
        (EVENT_ERROR, "Error"),
        (EVENT_STATE, "State Change"),
    ]

    VISIBILITY_CHOICES = [
        (VISIBILITY_USER, "User Visible"),
        (VISIBILITY_TOOL, "Tool Only"),
        (VISIBILITY_SYSTEM, "System Note"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="events")
    role = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Which layer emitted the event (frontman/caller/runner).",
    )
    event_type = models.CharField(max_length=32, choices=EVENT_CHOICES, default=EVENT_INFO)
    visibility = models.CharField(
        max_length=32, choices=VISIBILITY_CHOICES, default=VISIBILITY_SYSTEM
    )
    message = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    call_id = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["job", "created_at"]),
            models.Index(fields=["visibility"]),
        ]

    def __str__(self):
        return f"{self.job_id} {self.event_type}"


class OrchestrationSetting(models.Model):
    """
    Simple key/value store for runtime-configurable orchestration settings.
    """

    key = models.CharField(max_length=255, unique=True)
    value = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]
        indexes = [
            models.Index(fields=["key"]),
        ]

    def __str__(self):
        return f"{self.key}"


class UsageEvent(models.Model):
    """
    Tracks token usage per OpenAI call for observability.
    """

    SOURCE_CHOICES = [
        ("frontman_decision", "Frontman Decision"),
        ("frontman_generate", "Frontman Generate"),
        ("caller_plan", "Caller Plan"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=64, choices=SOURCE_CHOICES)
    model = models.CharField(max_length=128, blank=True, default="")
    cache_mode = models.CharField(max_length=32, blank=True, default="")
    prompt_tokens = models.IntegerField(default=0)
    cached_prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    prompt_cache_key = models.CharField(max_length=255, blank=True, default="")
    prompt_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    completion_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    job = models.ForeignKey(
        Job, null=True, blank=True, on_delete=models.SET_NULL, related_name="usage_events"
    )
    chat = models.ForeignKey(
        Chat, null=True, blank=True, on_delete=models.SET_NULL, related_name="usage_events"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["source"]),
            models.Index(fields=["model"]),
        ]

    def __str__(self):
        return f"{self.source} {self.created_at}"


class SoftEvent(models.Model):
    """
    Flexible, user-intent tasks that can be scheduled into free time.
    """

    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_ARCHIVED = "archived"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    preferred_duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Preferred session duration in minutes.",
    )
    min_duration_minutes = models.PositiveIntegerField(
        default=30,
        help_text="Minimum acceptable duration; scheduler will pack shorter slots if needed.",
    )
    soft_deadline = models.DateTimeField(null=True, blank=True)
    hard_deadline = models.DateTimeField(null=True, blank=True)
    frequency = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Optional recurrence description (e.g., weekly, monthly).",
    )
    deferral_limit = models.PositiveIntegerField(default=3)
    priority = models.IntegerField(default=0, help_text="Higher = more urgent/important.")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    metadata = models.JSONField(default=dict, blank=True)
    chat = models.ForeignKey(
        Chat, null=True, blank=True, on_delete=models.SET_NULL, related_name="soft_events"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["soft_deadline"]),
            models.Index(fields=["hard_deadline"]),
            models.Index(fields=["priority"]),
        ]

    def __str__(self):
        return f"{self.title}"


class Objective(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_PAUSED = "paused"
    STATUS_CANCELED = "canceled"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_CANCELED, "Canceled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    deadline_at = models.DateTimeField(null=True, blank=True)
    estimated_effort_minutes = models.PositiveIntegerField(null=True, blank=True)
    remaining_effort_minutes = models.PositiveIntegerField(null=True, blank=True)
    priority = models.IntegerField(default=0)
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    chat = models.ForeignKey(
        Chat, null=True, blank=True, on_delete=models.SET_NULL, related_name="objectives"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["deadline_at", "-priority", "created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["deadline_at"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["parent"]),
        ]

    def __str__(self):
        return self.title


class ObjectiveTask(models.Model):
    STATUS_TODO = "todo"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE = "done"
    STATUS_BLOCKED = "blocked"
    STATUS_CANCELED = "canceled"

    STATUS_CHOICES = [
        (STATUS_TODO, "To Do"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_DONE, "Done"),
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_CANCELED, "Canceled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    objective = models.ForeignKey(Objective, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_TODO)
    estimated_effort_minutes = models.PositiveIntegerField(null=True, blank=True)
    remaining_effort_minutes = models.PositiveIntegerField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["objective", "sort_order", "created_at"]
        indexes = [
            models.Index(fields=["objective", "status"]),
            models.Index(fields=["due_at"]),
        ]

    def __str__(self):
        return f"{self.objective.title} — {self.title}"


class ObjectiveLog(models.Model):
    KIND_WORK = "work"
    KIND_NOTE = "note"
    KIND_PROGRESS = "progress"
    KIND_DECISION = "decision"
    KIND_BLOCKER = "blocker"

    KIND_CHOICES = [
        (KIND_WORK, "Work"),
        (KIND_NOTE, "Note"),
        (KIND_PROGRESS, "Progress"),
        (KIND_DECISION, "Decision"),
        (KIND_BLOCKER, "Blocker"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    objective = models.ForeignKey(Objective, on_delete=models.CASCADE, related_name="logs")
    task = models.ForeignKey(
        ObjectiveTask,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="logs",
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default=KIND_NOTE)
    text = models.TextField(blank=True, default="")
    minutes_spent = models.PositiveIntegerField(null=True, blank=True)
    logged_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-logged_at", "-created_at"]
        indexes = [
            models.Index(fields=["objective", "logged_at"]),
            models.Index(fields=["kind"]),
        ]

    def __str__(self):
        return f"{self.objective.title} [{self.kind}]"


class SoftEventSlot(models.Model):
    """
    Planned instance of a soft event in time (not necessarily written to calendar).
    """

    STATUS_PLANNED = "planned"
    STATUS_COMPLETED = "completed"
    STATUS_DEFERRED = "deferred"
    STATUS_SKIPPED = "skipped"
    STATUS_PROMOTED = "promoted"
    STATUS_CANCELED = "canceled"

    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_DEFERRED, "Deferred"),
        (STATUS_SKIPPED, "Skipped"),
        (STATUS_PROMOTED, "Promoted to calendar"),
        (STATUS_CANCELED, "Canceled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    soft_event = models.ForeignKey(
        SoftEvent, on_delete=models.CASCADE, related_name="slots"
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    notify_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PLANNED)
    deferral_count = models.PositiveIntegerField(default=0)
    rationale = models.TextField(blank=True, default="")
    planner_trace_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Correlation id from planner decisions.",
    )
    call_made_at = models.DateTimeField(null=True, blank=True, help_text="When a call notification was made about this slot.")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_at"]
        indexes = [
            models.Index(fields=["start_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["notify_at"]),
            models.Index(fields=["call_made_at"]),
        ]

    def __str__(self):
        return f"{self.soft_event.title} @ {self.start_at}"


class SoftEventObjective(models.Model):
    ROLE_PRIMARY = "primary"
    ROLE_SECONDARY = "secondary"

    ROLE_CHOICES = [
        (ROLE_PRIMARY, "Primary"),
        (ROLE_SECONDARY, "Secondary"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    soft_event = models.ForeignKey(SoftEvent, on_delete=models.CASCADE, related_name="objective_links")
    objective = models.ForeignKey(Objective, on_delete=models.CASCADE, related_name="soft_event_links")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_PRIMARY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["soft_event", "objective"],
                name="unique_soft_event_objective_link",
            ),
        ]
        indexes = [
            models.Index(fields=["objective", "role"]),
        ]


class SoftEventTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    soft_event = models.ForeignKey(SoftEvent, on_delete=models.CASCADE, related_name="task_links")
    task = models.ForeignKey(ObjectiveTask, on_delete=models.CASCADE, related_name="soft_event_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["soft_event", "task"],
                name="unique_soft_event_task_link",
            ),
        ]
        indexes = [
            models.Index(fields=["task"]),
        ]


class ScheduledTask(models.Model):
    """
    Prompt-driven tasks executed by the Function Caller at a future time.
    """

    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELED = "canceled"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELED, "Canceled"),
    ]

    RECURRENCE_ONCE = "once"
    RECURRENCE_DAILY = "daily"
    RECURRENCE_WEEKLY = "weekly"
    RECURRENCE_MONTHLY = "monthly"

    RECURRENCE_CHOICES = [
        (RECURRENCE_ONCE, "Once"),
        (RECURRENCE_DAILY, "Daily"),
        (RECURRENCE_WEEKLY, "Weekly"),
        (RECURRENCE_MONTHLY, "Monthly"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prompt = models.TextField()
    recurrence = models.CharField(
        max_length=16, choices=RECURRENCE_CHOICES, default=RECURRENCE_ONCE
    )
    start_at = models.DateTimeField()
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    is_running = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_run_at", "-created_at"]
        indexes = [
            models.Index(fields=["status", "next_run_at"]),
            models.Index(fields=["is_running"]),
        ]

    def __str__(self):
        return f"ScheduledTask {self.id}"


class ScheduledTaskRun(models.Model):
    """
    Execution record for a scheduled task.
    """

    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(ScheduledTask, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    summary = models.TextField(blank=True, default="")
    error_summary = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["task", "started_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"ScheduledTaskRun {self.id}"


class ScheduledTaskLogEntry(models.Model):
    """
    Append-only log entries for scheduled task runs.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        ScheduledTaskRun, on_delete=models.CASCADE, related_name="log_entries"
    )
    role = models.CharField(max_length=32, blank=True, default="system")
    level = models.CharField(max_length=16, blank=True, default="info")
    message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["run", "created_at"]),
        ]

    def __str__(self):
        return f"{self.run_id} {self.level}"


class FrontmanPersona(models.Model):
    """
    Stores persona/instructions for the Front Man layer.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    instructions = models.TextField(
        help_text="Developer/system message describing tone, behavior, and guardrails."
    )
    postamble = models.TextField(
        blank=True,
        default="",
        help_text="Optional instructions appended after persona to further steer Front Man.",
    )
    is_active = models.BooleanField(
        default=False,
        help_text="If true, this persona is the active one used by Frontman.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return self.slug


class UserProfile(models.Model):
    """
    Stores core, always-on profile text for a user.
    """

    user_id = models.CharField(max_length=255, primary_key=True, default="default")
    core_text = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]

    def __str__(self):
        return f"Profile {self.user_id}"


class UserNote(models.Model):
    """
    Circumstantial user info with embeddings for semantic search.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.CharField(max_length=255, db_index=True, default="default")
    content_raw = models.TextField()
    content_canonical = models.TextField(blank=True, default="")
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    source = models.CharField(max_length=255, blank=True, default="")
    tags = ArrayField(models.CharField(max_length=64, blank=True), default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user_id", "created_at"]),
            models.Index(fields=["deleted_at"]),
        ]

    def __str__(self):
        return f"Note {self.id}"


class PushToken(models.Model):
    """
    Stores device push tokens for notifications.
    """

    PLATFORM_CHOICES = [
        ("ios", "iOS"),
        ("android", "Android"),
        ("web", "Web"),
        ("unknown", "Unknown"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token = models.TextField(unique=True)
    platform = models.CharField(max_length=32, choices=PLATFORM_CHOICES, default="unknown")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["platform"]),
        ]

    def __str__(self):
        return f"{self.platform} {self.token[:12]}"


class UserMessage(models.Model):
    """
    Standalone inbox messages not tied to chats.
    """

    KIND_INFO = "info"
    KIND_CALL_MISSED = "call_missed"
    KIND_CALL_TEXT = "call_text"

    KIND_CHOICES = [
        (KIND_INFO, "Info"),
        (KIND_CALL_MISSED, "Call missed"),
        (KIND_CALL_TEXT, "Call text"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default=KIND_INFO)
    metadata = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["read_at"]),
        ]

    def __str__(self):
        return f"{self.kind}: {self.title or self.body[:40]}"


class CallSession(models.Model):
    """
    In-app voice call session with a goal and transcript.
    """

    STATUS_SCHEDULED = "scheduled"
    STATUS_RINGING = "ringing"
    STATUS_IN_CALL = "in_call"
    STATUS_MISSED = "missed"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELED = "canceled"

    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_RINGING, "Ringing"),
        (STATUS_IN_CALL, "In call"),
        (STATUS_MISSED, "Missed"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELED, "Canceled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    goal = models.TextField()
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    ringing_started_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    summary = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
            models.Index(fields=["status", "ringing_started_at"]),
        ]

    def __str__(self):
        return f"CallSession {self.id} [{self.status}]"


class CallTranscriptEntry(models.Model):
    """
    Transcript lines for a call session.
    """

    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(CallSession, on_delete=models.CASCADE, related_name="transcript_entries")
    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default="system")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session", "created_at"]),
        ]

    def __str__(self):
        return f"{self.session_id} {self.role}"
