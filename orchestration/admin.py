from django.contrib import admin

from orchestration.models import FrontmanPersona, Job, JobEvent, ToolFunction, ToolModule


@admin.register(ToolModule)
class ToolModuleAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "updated_at")
    search_fields = ("slug", "name", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ToolFunction)
class ToolFunctionAdmin(admin.ModelAdmin):
    list_display = ("manifest_id", "module", "name", "deprecated", "updated_at")
    search_fields = ("manifest_id", "name", "description")
    list_filter = ("module", "deprecated")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "module", "active_function", "chat", "session_id", "updated_at")
    search_fields = ("id", "trace_id", "session_id", "user_visible_summary")
    list_filter = ("status",)
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")


@admin.register(JobEvent)
class JobEventAdmin(admin.ModelAdmin):
    list_display = ("job", "event_type", "visibility", "role", "created_at")
    search_fields = ("job__id", "message", "call_id")
    list_filter = ("event_type", "visibility", "role")
    readonly_fields = ("created_at",)


@admin.register(FrontmanPersona)
class FrontmanPersonaAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "updated_at")
    search_fields = ("slug", "name", "description")
    readonly_fields = ("created_at", "updated_at")
