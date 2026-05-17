from django.contrib import admin

from study.models import (
    StudyCourse,
    StudyExam,
    StudyMaterial,
    StudyPlan,
    StudySessionLog,
    StudySessionTarget,
    StudyTopic,
    TopicMastery,
)


@admin.register(StudyCourse)
class StudyCourseAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "status", "term_start_date", "term_end_date", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "code")


@admin.register(StudyExam)
class StudyExamAdmin(admin.ModelAdmin):
    list_display = ("course", "title", "kind", "scheduled_at", "weight")
    list_filter = ("kind",)
    search_fields = ("title", "course__title", "course__code")


@admin.register(StudyTopic)
class StudyTopicAdmin(admin.ModelAdmin):
    list_display = ("course", "name", "order_index", "estimated_effort_minutes", "weight", "status")
    list_filter = ("status",)
    search_fields = ("name", "course__title", "course__code")


@admin.register(StudyMaterial)
class StudyMaterialAdmin(admin.ModelAdmin):
    list_display = (
        "course",
        "title",
        "kind",
        "ingestion_status",
        "page_count",
        "exam",
        "topic",
        "file_upload",
        "created_at",
    )
    list_filter = ("kind", "ingestion_status")
    search_fields = ("title", "course__title", "course__code")

    @admin.display(description="Uploaded file")
    def file_upload(self, obj):
        return obj.uploaded_file.name if obj.uploaded_file else ""


@admin.register(StudyPlan)
class StudyPlanAdmin(admin.ModelAdmin):
    list_display = ("course", "name", "status", "window_start", "window_end", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "course__title", "course__code")


@admin.register(StudySessionTarget)
class StudySessionTargetAdmin(admin.ModelAdmin):
    list_display = ("course", "plan", "target_date", "topic", "status", "target_preferred_minutes")
    list_filter = ("status",)
    search_fields = ("course__title", "course__code", "topic__name", "focus")


@admin.register(TopicMastery)
class TopicMasteryAdmin(admin.ModelAdmin):
    list_display = ("course", "topic", "mastery_score", "confidence_score", "evidence_count", "last_evidence_at")
    search_fields = ("course__title", "course__code", "topic__name")


@admin.register(StudySessionLog)
class StudySessionLogAdmin(admin.ModelAdmin):
    list_display = ("course", "topic", "result", "started_at", "ended_at", "actual_minutes")
    list_filter = ("result",)
    search_fields = ("course__title", "course__code", "topic__name", "notes")
