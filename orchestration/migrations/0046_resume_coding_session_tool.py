from django.db import migrations


MANIFEST_ID = "coding_sessions.resume_session"


def add_resume_tool(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    module = ToolModule.objects.get(slug="coding_sessions")
    instruction = (
        "Stopping a coding session is reversible. When the user asks to continue a stopped session, "
        "use resume_session so its saved Codex thread and history are retained."
    )
    if instruction not in module.caller_instructions:
        module.caller_instructions = f"{module.caller_instructions}\n{instruction}".strip()
        module.save(update_fields=["caller_instructions", "updated_at"])
    ToolFunction.objects.update_or_create(
        manifest_id=MANIFEST_ID,
        defaults={
            "module": module,
            "name": "Resume Session",
            "description": "Resume a stopped persistent Codex session with its saved thread and history.",
            "handler_ref": "orchestration.tools.coding_sessions.resume_session",
            "params_schema": {
                "type": "object",
                "properties": {
                    "session": {"type": "string", "description": "Coding session display name or UUID"}
                },
                "required": ["session"],
            },
            "return_schema": {},
            "deprecated": False,
        },
    )


def remove_resume_tool(apps, schema_editor):
    apps.get_model("orchestration", "ToolFunction").objects.filter(manifest_id=MANIFEST_ID).delete()


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0045_feature_delegation_tools")]
    operations = [migrations.RunPython(add_resume_tool, remove_resume_tool)]
