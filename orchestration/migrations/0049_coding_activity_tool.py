from django.db import migrations


MANIFEST_ID = "coding_sessions.get_activity"


def add_activity_tool(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    module = ToolModule.objects.get(slug="coding_sessions")
    module.caller_instructions = (
        module.caller_instructions
        + " Use get_activity when the user asks what coding work or delegations are running, "
        "their current statuses, or for recent coding and QA logs."
    )
    module.save(update_fields=["caller_instructions", "updated_at"])
    ToolFunction.objects.update_or_create(
        manifest_id=MANIFEST_ID,
        defaults={
            "module": module,
            "name": "Get Coding Activity",
            "description": "Show running coding sessions and feature delegations with recent coder and QA logs.",
            "handler_ref": "orchestration.tools.coding_sessions.get_activity",
            "params_schema": {
                "type": "object",
                "properties": {
                    "include_inactive": {"type": "boolean", "default": False},
                    "recent_log_chars": {"type": "integer", "minimum": 500, "maximum": 20000, "default": 6000},
                },
            },
            "return_schema": {},
            "deprecated": False,
        },
    )


def remove_activity_tool(apps, schema_editor):
    apps.get_model("orchestration", "ToolFunction").objects.filter(manifest_id=MANIFEST_ID).delete()


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0048_functional_file_handler")]
    operations = [migrations.RunPython(add_activity_tool, remove_activity_tool)]
