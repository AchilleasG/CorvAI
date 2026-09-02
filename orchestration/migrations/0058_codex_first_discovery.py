from django.db import migrations

CODEX_GUIDANCE = " Codex-first discovery rule: this supersedes direct SSH inspection. For every request to find, locate, search for, or discover a project, repository, file, or unknown path, use a coding_sessions delegation. If the user names an SSH machine, reuse a coding session on that exact machine, or create one there, before delegating. Strongly prefer Codex for multi-step investigation and non-text file generation."
SSH_GUIDANCE = " Codex-first boundary: never use run_command to find, locate, search for, or discover projects, repositories, files, or unknown paths. Delegate through coding_sessions on the requested machine. Direct SSH is reserved for a single bounded command whose exact path and command are already known, or a narrow status check."
RUN_DESCRIPTION = "Run one bounded command only when the exact command and path are already known. Do not use this for finding, locating, searching, or discovering projects, repositories, files, or unknown paths; use coding_sessions delegation on the requested machine for those tasks and multi-step work."

def configure(apps, schema_editor):
    Module=apps.get_model("orchestration","ToolModule"); Function=apps.get_model("orchestration","ToolFunction")
    for slug, guidance in (("coding_sessions",CODEX_GUIDANCE),("ssh_connections",SSH_GUIDANCE)):
        module=Module.objects.get(slug=slug)
        if guidance not in module.caller_instructions:
            module.caller_instructions=module.caller_instructions.rstrip()+guidance; module.save(update_fields=["caller_instructions","updated_at"])
    command=Function.objects.get(manifest_id="ssh_connections.run_command"); command.description=RUN_DESCRIPTION; command.save(update_fields=["description","updated_at"])

class Migration(migrations.Migration):
    dependencies=[("orchestration","0057_delegations_wait_by_default")]
    operations=[migrations.RunPython(configure,migrations.RunPython.noop)]
