from __future__ import annotations

from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AssistantPersona(TimestampedModel):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    mission = models.TextField(blank=True)
    system_prompt = models.TextField()
    style_guidelines = models.JSONField(default=list, blank=True)
    closing_phrase = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


class PersonaUserProfile(TimestampedModel):
    persona = models.ForeignKey(
        AssistantPersona, on_delete=models.CASCADE, related_name="user_profiles"
    )
    profile_id = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    role = models.CharField(max_length=255, blank=True)
    summary = models.TextField(blank=True)
    goals = models.JSONField(default=list, blank=True)
    preferences = models.JSONField(default=list, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        unique_together = ("persona", "profile_id")

    def __str__(self):
        return f"{self.name} ({self.profile_id})"


class MCPModule(TimestampedModel):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField()

    def __str__(self):
        return self.name


class ModuleFunction(TimestampedModel):
    module = models.ForeignKey(
        MCPModule, on_delete=models.CASCADE, related_name="functions"
    )
    slug = models.SlugField()
    name = models.CharField(max_length=120)
    description = models.TextField()
    knowledge_requirements = models.JSONField(default=list, blank=True)
    result_description = models.TextField(blank=True)

    class Meta:
        unique_together = ("module", "slug")

    def __str__(self):
        return f"{self.module.slug}.{self.slug}"


class ModuleFunctionParameter(TimestampedModel):
    function = models.ForeignKey(
        ModuleFunction, on_delete=models.CASCADE, related_name="parameters"
    )
    name = models.CharField(max_length=120)
    data_type = models.CharField(max_length=60, default="string")
    description = models.TextField(blank=True)
    required = models.BooleanField(default=True)
    default_value = models.CharField(max_length=255, blank=True)
    allowed_values = models.JSONField(default=list, blank=True)
    example = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("function", "name")

    def __str__(self):
        return f"{self.function}.{self.name}"


class ModuleFunctionErrorPolicy(TimestampedModel):
    function = models.ForeignKey(
        ModuleFunction, on_delete=models.CASCADE, related_name="error_policies"
    )
    code = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    handling_notes = models.TextField(blank=True)
    severity = models.CharField(
        max_length=32,
        choices=[("info", "Info"), ("warn", "Warn"), ("error", "Error")],
        default="error",
    )

    class Meta:
        unique_together = ("function", "code")

    def __str__(self):
        return f"{self.function}.{self.code}"


class TaskPlan(TimestampedModel):
    STATUS_CHOICES = [
        ("idle", "Idle"),
        ("awaiting_info", "Awaiting Info"),
        ("ready", "Ready"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("error", "Error"),
    ]

    chat = models.ForeignKey(
        "chat.Chat", on_delete=models.CASCADE, related_name="task_plans"
    )
    persona = models.ForeignKey(
        AssistantPersona, null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="idle")
    plan = models.JSONField(default=dict, blank=True)
    missing_information = models.JSONField(default=list, blank=True)
    last_error = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"TaskPlan({self.chat_id}, {self.status})"


class FunctionExecutionLog(TimestampedModel):
    STATUS_CHOICES = [
        ("success", "Success"),
        ("error", "Error"),
    ]

    chat = models.ForeignKey(
        "chat.Chat", on_delete=models.CASCADE, related_name="function_logs"
    )
    function = models.ForeignKey(
        ModuleFunction, null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        target = self.function or "unknown"
        return f"{target} ({self.status})"
