from django.db import migrations


GUIDANCE = (
    " Machine routing rules: when the user names, describes, or clearly refers to a saved machine, "
    "pass that machine's exact saved name or id in every related SSH tool call. A default machine is "
    "only a fallback when the user gives no machine preference; it must never override an explicit "
    "target. If a name is ambiguous or unrecognized, or if machine suitability must be compared, call "
    "ssh_connections.list_machines first and choose from its returned exact names, notes, permissions, "
    "and default status."
)


def strengthen_ssh_routing(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module = ToolModule.objects.get(slug="ssh_connections")
    if GUIDANCE.strip() not in module.caller_instructions:
        module.caller_instructions = module.caller_instructions.rstrip() + GUIDANCE
        module.save(update_fields=["caller_instructions", "updated_at"])

    listing = ToolFunction.objects.get(manifest_id="ssh_connections.list_machines")
    listing.description = (
        "List saved SSH machines with exact names, ids, default status, permissions, and operational "
        "notes. Call this first when a requested machine is uncertain or when selecting the most "
        "suitable machine for a task."
    )
    listing.save(update_fields=["description", "updated_at"])

    command = ToolFunction.objects.get(manifest_id="ssh_connections.run_command")
    command.description = (
        "Run an exact bounded shell command on a saved SSH machine. Always pass the exact machine name/id "
        "when the user identifies one; omit it for the default only when no preference was given. "
        "Call list_machines first if the target is uncertain."
    )
    command.examples = [
        {
            "user_prompt": "Search for ExamSense on Animus Server",
            "params": {"machine": "Animus Server", "command": "find ~/Projects -maxdepth 3 -iname '*examsense*'"},
        },
        {
            "user_prompt": "Use whichever machine is best to calculate this",
            "params": {"command": "python3 -c 'print(sum(range(101)))'"},
        },
    ]
    command.save(update_fields=["description", "examples", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0053_ssh_machine_notes_context")]
    operations = [migrations.RunPython(strengthen_ssh_routing, migrations.RunPython.noop)]
