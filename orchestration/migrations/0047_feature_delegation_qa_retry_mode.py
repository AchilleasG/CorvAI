from django.db import migrations


MANIFEST_ID = "coding_sessions.resume_feature_delegation"


def add_qa_retry_mode(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    module = ToolModule.objects.get(slug="coding_sessions")
    instruction = (
        "When a feature is waiting because its latest QA run was blocked or errored, retry QA with "
        "resume_feature_delegation mode='qa'; do not send infrastructure failures back to the coder. "
        "Use mode='coding' only when application changes are actually required."
    )
    if instruction not in module.caller_instructions:
        module.caller_instructions = f"{module.caller_instructions}\n{instruction}".strip()
        module.save(update_fields=["caller_instructions", "updated_at"])
    ToolFunction.objects.filter(manifest_id=MANIFEST_ID).update(
        description=(
            "Resume a waiting, failed, or stopped feature. Retry blocked QA directly, or explicitly "
            "return to coding when application changes are needed."
        ),
        params_schema={
            "type": "object",
            "properties": {
                "delegation": {"type": "string", "description": "Feature display name or UUID"},
                "decision": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["auto", "qa", "coding"],
                    "default": "auto",
                },
            },
            "required": ["delegation"],
        },
    )


def remove_qa_retry_mode(apps, schema_editor):
    apps.get_model("orchestration", "ToolFunction").objects.filter(
        manifest_id=MANIFEST_ID
    ).update(
        description="Resume a feature after a user decision or interruption.",
        params_schema={
            "type": "object",
            "properties": {
                "delegation": {"type": "string"},
                "decision": {"type": "string"},
            },
            "required": ["delegation"],
        },
    )


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0046_resume_coding_session_tool")]
    operations = [migrations.RunPython(add_qa_retry_mode, remove_qa_retry_mode)]
