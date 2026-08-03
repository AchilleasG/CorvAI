from __future__ import annotations

import uuid

from django.db import models

from ssh_connections.models import SshMachine


class CodingSession(models.Model):
    STATUS_READY = "ready"
    STATUS_RUNNING = "running"
    STATUS_NEEDS_INPUT = "needs_input"
    STATUS_DIRECT = "direct"
    STATUS_FAILED = "failed"
    STATUS_STOPPED = "stopped"
    STATUS_CHOICES = [
        (STATUS_READY, "Ready"),
        (STATUS_RUNNING, "Running"),
        (STATUS_NEEDS_INPUT, "Needs input"),
        (STATUS_DIRECT, "Direct CLI"),
        (STATUS_FAILED, "Failed"),
        (STATUS_STOPPED, "Stopped"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    machine = models.ForeignKey(SshMachine, on_delete=models.PROTECT, related_name="coding_sessions")
    remote_working_directory = models.CharField(max_length=1024, default="~")
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_READY)
    permission_mode = models.CharField(max_length=32, default="danger-full-access")
    codex_thread_id = models.CharField(max_length=128, blank=True, default="")
    tmux_session_name = models.CharField(max_length=128, blank=True, default="")
    last_summary = models.TextField(blank=True, default="")
    pending_question = models.TextField(blank=True, default="")
    pending_options = models.JSONField(default=list, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    stopped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["status", "updated_at"], name="coding_codi_status_669a38_idx")]

    def __str__(self):
        return f"{self.name} on {self.machine.name}"


class CodingTurn(models.Model):
    SOURCE_CORV = "corv"
    SOURCE_UI = "ui"
    SOURCE_DECISION = "decision"
    SOURCE_FEATURE = "feature"
    SOURCE_CHOICES = [
        (SOURCE_CORV, "Corv"),
        (SOURCE_UI, "Coding module"),
        (SOURCE_DECISION, "Decision"),
        (SOURCE_FEATURE, "Feature delegation"),
    ]
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_NEEDS_INPUT = "needs_input"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_NEEDS_INPUT, "Needs input"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(CodingSession, on_delete=models.CASCADE, related_name="turns")
    source = models.CharField(max_length=24, choices=SOURCE_CHOICES, default=SOURCE_UI)
    prompt = models.TextField()
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    codex_thread_id = models.CharField(max_length=128, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    question = models.TextField(blank=True, default="")
    options = models.JSONField(default=list, blank=True)
    event_log = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["session", "created_at"], name="coding_codi_session_c771b2_idx")]

    def __str__(self):
        return f"{self.session.name}: {self.prompt[:80]}"


class FeatureDelegation(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_CODING = "coding"
    STATUS_QA = "qa"
    STATUS_FIXING = "fixing"
    STATUS_NEEDS_INPUT = "needs_input"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_STOPPED = "stopped"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_CODING, "Coding"),
        (STATUS_QA, "QA"),
        (STATUS_FIXING, "Fixing"),
        (STATUS_NEEDS_INPUT, "Needs input"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_STOPPED, "Stopped"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(CodingSession, on_delete=models.CASCADE, related_name="delegations")
    title = models.CharField(max_length=200)
    description = models.TextField()
    acceptance_criteria = models.JSONField(default=list)
    qa_enabled = models.BooleanField(default=True)
    max_iterations = models.PositiveSmallIntegerField(default=6)
    current_iteration = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    qa_thread_id = models.CharField(max_length=128, blank=True, default="")
    coding_turn_ids = models.JSONField(default=list, blank=True)
    implementation_summary = models.TextField(blank=True, default="")
    qa_summary = models.TextField(blank=True, default="")
    pending_question = models.TextField(blank=True, default="")
    pending_options = models.JSONField(default=list, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["session", "status"], name="coding_feat_session_7a9ca4_idx")]

    def __str__(self):
        return f"{self.title} ({self.status})"


class FeatureQaRun(models.Model):
    STATUS_RUNNING = "running"
    STATUS_PASSED = "passed"
    STATUS_FAILED = "failed"
    STATUS_BLOCKED = "blocked"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "Running"),
        (STATUS_PASSED, "Passed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_ERROR, "Error"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    delegation = models.ForeignKey(FeatureDelegation, on_delete=models.CASCADE, related_name="qa_runs")
    iteration = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    summary = models.TextField(blank=True, default="")
    failures = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    question = models.TextField(blank=True, default="")
    options = models.JSONField(default=list, blank=True)
    event_log = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["delegation", "iteration"], name="coding_feat_delegat_74c1d8_idx")]

    def __str__(self):
        return f"{self.delegation.title}: QA {self.iteration} ({self.status})"
