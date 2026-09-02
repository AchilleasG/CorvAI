from django.db import migrations


GUIDANCE = (
    " Prefer Codex delegation over direct SSH for repository work, broad or uncertain filesystem "
    "discovery, multi-step investigation, binary artifact generation, or anything requiring iterative "
    "commands and judgment. Before creating a delegation mid-chat, ask whether the user wants Corv to "
    "wait and report back or start it without waiting, unless already specified. If they choose wait, "
    "pass wait_for_completion=true. This creates a durable chat watcher: do not poll repeatedly. Corv "
    "will post completion, failure, or any Codex question/options into the originating chat."
)


def configure_wait(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    module = ToolModule.objects.get(slug="coding_sessions")
    if GUIDANCE.strip() not in module.caller_instructions:
        module.caller_instructions = module.caller_instructions.rstrip() + GUIDANCE
        module.save(update_fields=["caller_instructions", "updated_at"])
    for manifest_id in ["coding_sessions.delegate_task", "coding_sessions.delegate_feature"]:
        tool = ToolFunction.objects.get(manifest_id=manifest_id)
        schema = tool.params_schema or {"type": "object", "properties": {}}
        schema.setdefault("properties", {})["wait_for_completion"] = {
            "type": "boolean",
            "default": False,
            "description": "True only after the user chooses to have Corv report completion or questions back into this chat",
        }
        tool.params_schema = schema
        tool.save(update_fields=["params_schema", "updated_at"])

    command = ToolFunction.objects.get(manifest_id="ssh_connections.run_command")
    if "exact bounded shell command" not in command.description:
        command.description = command.description.replace("exact bounded command", "exact bounded shell command")
        command.save(update_fields=["description", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0054_explicit_ssh_machine_routing"), ("coding", "0005_codingdelegationwatch")]
    operations = [migrations.RunPython(configure_wait, migrations.RunPython.noop)]
