from django.contrib import admin

from ssh_connections.models import SshCommandRecord, SshMachine


@admin.register(SshMachine)
class SshMachineAdmin(admin.ModelAdmin):
    list_display = ("name", "host", "port", "username", "auth_type", "allow_ai_commands", "is_default", "last_connected_at")
    search_fields = ("name", "host", "username", "notes")
    list_filter = ("auth_type", "allow_ai_commands", "is_default")
    exclude = ("credential_encrypted",)
    readonly_fields = ("host_key_fingerprint", "last_connected_at", "last_error", "created_at", "updated_at")


@admin.register(SshCommandRecord)
class SshCommandRecordAdmin(admin.ModelAdmin):
    list_display = ("machine", "source", "command", "exit_status", "succeeded", "created_at")
    search_fields = ("machine__name", "command", "error_summary")
    list_filter = ("source", "succeeded")
    readonly_fields = ("created_at",)
