from __future__ import annotations

import uuid
from django.db import models
from django.db.models import Q
from chat.models import Chat


class StudyCourse(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_ARCHIVED = "archived"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    code = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    term_start_date = models.DateField(null=True, blank=True)
    term_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    chat = models.ForeignKey(Chat, null=True, blank=True, on_delete=models.SET_NULL, related_name="study_courses")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["code"]),
        ]

    def __str__(self):
        return self.code or self.title


class StudyExam(models.Model):
    KIND_MIDTERM = "midterm"
    KIND_FINAL = "final"
    KIND_QUIZ = "quiz"
    KIND_PRACTICAL = "practical"
    KIND_OTHER = "other"

    KIND_CHOICES = [
        (KIND_MIDTERM, "Midterm"),
        (KIND_FINAL, "Final"),
        (KIND_QUIZ, "Quiz"),
        (KIND_PRACTICAL, "Practical"),
        (KIND_OTHER, "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(StudyCourse, on_delete=models.CASCADE, related_name="exams")
    title = models.CharField(max_length=255)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default=KIND_OTHER)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    weight = models.FloatField(default=1.0)
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_at", "title"]
        indexes = [
            models.Index(fields=["course", "kind"]),
            models.Index(fields=["scheduled_at"]),
        ]

    def __str__(self):
        return f"{self.course} — {self.title}"


class StudyTopic(models.Model):
    STATUS_NOT_STARTED = "not_started"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_REVIEW = "review"
    STATUS_MASTERED = "mastered"

    STATUS_CHOICES = [
        (STATUS_NOT_STARTED, "Not Started"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_REVIEW, "Review"),
        (STATUS_MASTERED, "Mastered"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(StudyCourse, on_delete=models.CASCADE, related_name="topics")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    summary = models.TextField(blank=True, default="", help_text="Human-readable bullet-point summary of what's covered in this topic")
    order_index = models.PositiveIntegerField(default=0)
    estimated_effort_minutes = models.PositiveIntegerField(default=60)
    weight = models.FloatField(default=1.0)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_NOT_STARTED)
    passed = models.BooleanField(default=False)
    passed_at = models.DateTimeField(null=True, blank=True)
    grade = models.FloatField(null=True, blank=True)
    prerequisites = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="dependent_topics")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["course", "order_index", "name"]
        constraints = [
            models.UniqueConstraint(fields=["course", "name"], name="unique_topic_per_course"),
        ]
        indexes = [
            models.Index(fields=["course", "order_index"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.course} — {self.name}"


class StudyMaterial(models.Model):
    KIND_LECTURE = "lecture"
    KIND_LECTURE_PDF = KIND_LECTURE
    KIND_SLIDES = "slides"
    KIND_PAST_EXAM = "past_exam"
    KIND_NOTES = "notes"
    KIND_LINK = "link"
    KIND_OTHER = "other"

    KIND_CHOICES = [
        (KIND_LECTURE, "Lecture"),
        (KIND_SLIDES, "Slides"),
        (KIND_PAST_EXAM, "Past Exam"),
        (KIND_NOTES, "Notes"),
        (KIND_LINK, "Link"),
        (KIND_OTHER, "Other"),
    ]

    INGESTION_PENDING = "pending"
    INGESTION_PROCESSING = "processing"
    INGESTION_PROCESSED = "processed"
    INGESTION_FAILED = "failed"

    INGESTION_CHOICES = [
        (INGESTION_PENDING, "Pending"),
        (INGESTION_PROCESSING, "Processing"),
        (INGESTION_PROCESSED, "Processed"),
        (INGESTION_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(StudyCourse, on_delete=models.CASCADE, related_name="materials")
    topic = models.ForeignKey(StudyTopic, null=True, blank=True, on_delete=models.SET_NULL, related_name="materials")
    exam = models.ForeignKey(StudyExam, null=True, blank=True, on_delete=models.SET_NULL, related_name="materials")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default=KIND_OTHER)
    title = models.CharField(max_length=255)
    source_url = models.URLField(blank=True, default="")
    uploaded_file = models.FileField(upload_to="study/materials/", blank=True, null=True)
    file_path = models.CharField(max_length=512, blank=True, default="")
    ingestion_status = models.CharField(max_length=32, choices=INGESTION_CHOICES, default=INGESTION_PENDING)
    page_count = models.PositiveIntegerField(default=0)
    converted_markdown = models.TextField(blank=True, default="")
    solved_markdown = models.TextField(blank=True, default="")
    theory_markdown = models.TextField(blank=True, default="")
    extracted_data = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True, default="")
    raw_text = models.TextField(blank=True, default="")
    parsed_text = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["course", "kind"]),
            models.Index(fields=["ingestion_status"]),
        ]

    def __str__(self):
        return f"{self.course} — {self.title}"


class StudyPlan(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_SUPERSEDED = "superseded"
    STATUS_ARCHIVED = "archived"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_SUPERSEDED, "Superseded"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(StudyCourse, on_delete=models.CASCADE, related_name="plans")
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    summary = models.TextField(blank=True, default="")
    plan_json = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=64, blank=True, default="system")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["course"],
                condition=Q(status="active"),
                name="unique_active_study_plan_per_course",
            )
        ]
        indexes = [
            models.Index(fields=["course", "status"]),
            models.Index(fields=["window_start", "window_end"]),
        ]

    def __str__(self):
        return f"{self.course} — {self.name}"


class StudySessionTarget(models.Model):
    STATUS_PLANNED = "planned"
    STATUS_SCHEDULED = "scheduled"
    STATUS_COMPLETED = "completed"
    STATUS_MISSED = "missed"
    STATUS_CANCELED = "canceled"

    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned"),
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_MISSED, "Missed"),
        (STATUS_CANCELED, "Canceled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(StudyPlan, on_delete=models.CASCADE, related_name="session_targets")
    course = models.ForeignKey(StudyCourse, on_delete=models.CASCADE, related_name="session_targets")
    exam = models.ForeignKey(StudyExam, null=True, blank=True, on_delete=models.SET_NULL, related_name="session_targets")
    topic = models.ForeignKey(StudyTopic, null=True, blank=True, on_delete=models.SET_NULL, related_name="session_targets")
    target_date = models.DateField()
    target_preferred_minutes = models.PositiveIntegerField(default=60)
    target_min_minutes = models.PositiveIntegerField(default=30)
    focus = models.TextField(blank=True, default="")
    outcome = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PLANNED)
    soft_event_ref = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_date", "created_at"]
        indexes = [
            models.Index(fields=["plan", "target_date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["course", "target_date"]),
        ]

    def __str__(self):
        return f"{self.course} — {self.target_date}"


class TopicMastery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(StudyCourse, on_delete=models.CASCADE, related_name="mastery_entries")
    topic = models.ForeignKey(StudyTopic, on_delete=models.CASCADE, related_name="mastery_entries")
    mastery_score = models.FloatField(default=0.0)
    confidence_score = models.FloatField(default=0.0)
    evidence_count = models.PositiveIntegerField(default=0)
    last_evidence_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["course", "topic"]
        constraints = [
            models.UniqueConstraint(fields=["course", "topic"], name="unique_topic_mastery_per_course"),
        ]
        indexes = [
            models.Index(fields=["course", "topic"]),
            models.Index(fields=["mastery_score"]),
        ]

    def __str__(self):
        return f"{self.course} — {self.topic}"


class StudySessionLog(models.Model):
    RESULT_COMPLETED = "completed"
    RESULT_PARTIAL = "partial"
    RESULT_SKIPPED = "skipped"

    RESULT_CHOICES = [
        (RESULT_COMPLETED, "Completed"),
        (RESULT_PARTIAL, "Partial"),
        (RESULT_SKIPPED, "Skipped"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(StudyCourse, on_delete=models.CASCADE, related_name="session_logs")
    plan = models.ForeignKey(StudyPlan, null=True, blank=True, on_delete=models.SET_NULL, related_name="session_logs")
    exam = models.ForeignKey(StudyExam, null=True, blank=True, on_delete=models.SET_NULL, related_name="session_logs")
    topic = models.ForeignKey(StudyTopic, null=True, blank=True, on_delete=models.SET_NULL, related_name="session_logs")
    target = models.ForeignKey(StudySessionTarget, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs")
    soft_event_ref = models.UUIDField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    actual_minutes = models.PositiveIntegerField(default=0)
    self_rating = models.PositiveIntegerField(null=True, blank=True)
    result = models.CharField(max_length=32, choices=RESULT_CHOICES, default=RESULT_PARTIAL)
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["course", "created_at"]),
            models.Index(fields=["result"]),
            models.Index(fields=["topic", "created_at"]),
        ]

    def __str__(self):
        return f"{self.course} — {self.result}"
