from django.db import migrations


GUIDANCE = (
    " Machine notes are durable user-managed operational context and are loaded before SSH planning. "
    "Use them when selecting a machine and constructing commands. When you discover a useful durable "
    "fact about a machine, call ssh_connections.set_machine_notes in append mode. Use replace only to "
    "correct stale notes, preserve unrelated facts, and never store credentials or secrets."
)


def configure_machine_notes(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    from orchestration.registry import FunctionRegistry

    module = ToolModule.objects.get(slug="ssh_connections")
    if GUIDANCE.strip() not in module.caller_instructions:
        module.caller_instructions = module.caller_instructions.rstrip() + GUIDANCE
        module.save(update_fields=["caller_instructions", "updated_at"])

    registered = FunctionRegistry.get("ssh_connections.set_machine_notes")
    ToolFunction.objects.update_or_create(
        manifest_id=registered.manifest_id,
        defaults={
            "module": module,
            "name": "Set SSH Machine Notes",
            "description": registered.description,
            "params_schema": registered.params_schema,
            "return_schema": registered.return_schema or {},
            "handler_ref": registered.handler_ref,
            "tags": ["ssh", "machines", "context"],
            "examples": [{
                "user_prompt": "Remember that this machine logs in as root and has no sudo",
                "params": {
                    "machine": "1984",
                    "notes": "Runs as root; sudo is not installed. Use apt-get directly.",
                    "mode": "append",
                },
            }],
            "deprecated": False,
        },
    )


def reverse_machine_notes(apps, schema_editor):
    apps.get_model("orchestration", "ToolFunction").objects.filter(
        manifest_id="ssh_connections.set_machine_notes"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0052_ssh_file_fetch_guidance")]
    operations = [migrations.RunPython(configure_machine_notes, reverse_machine_notes)]
