from django.contrib import admin

from coding.models import CodingSession, CodingTurn, FeatureDelegation, FeatureQaRun


@admin.register(CodingSession)
class CodingSessionAdmin(admin.ModelAdmin):
    list_display = ("name", "machine", "status", "permission_mode", "updated_at")
    list_filter = ("status", "permission_mode")
    search_fields = ("name", "machine__name", "codex_thread_id")


@admin.register(CodingTurn)
class CodingTurnAdmin(admin.ModelAdmin):
    list_display = ("session", "source", "status", "created_at", "completed_at")
    list_filter = ("source", "status")
    search_fields = ("prompt", "summary", "question", "error")


@admin.register(FeatureDelegation)
class FeatureDelegationAdmin(admin.ModelAdmin):
    list_display = ("title", "session", "status", "qa_enabled", "current_iteration", "updated_at")
    list_filter = ("status", "qa_enabled")
    search_fields = ("title", "description", "session__name")


@admin.register(FeatureQaRun)
class FeatureQaRunAdmin(admin.ModelAdmin):
    list_display = ("delegation", "iteration", "status", "started_at", "completed_at")
    list_filter = ("status",)
    search_fields = ("delegation__title", "summary", "error")
