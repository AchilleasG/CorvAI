from __future__ import annotations

import uuid
from django.db import models

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
