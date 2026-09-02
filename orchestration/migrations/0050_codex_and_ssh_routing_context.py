from django.db import migrations


CODING_GUIDANCE = (
    " For a small task on an existing coding session, use delegate_task to send the exact instruction "
    "into that open Codex session. It retains the saved Codex thread, repository context, and remote "
    "working directory, so it is the easy path for a quick code edit, investigation, test, or command "
    "that benefits from Codex reasoning. Use delegate_feature only for substantial autonomous work with "
    "acceptance criteria and QA. For a simple exact shell command that needs no code reasoning, prefer "
    "ssh_connections.run_command instead."
)

SSH_GUIDANCE = (
    " Prefer run_command for simple, exact, bounded inspection or operational commands such as checking "
    "disk space, service status, logs, or a known command. Use coding_sessions.delegate_task instead when "
    "the request needs repository understanding, code edits, debugging, or test-driven reasoning."
)


def update_routing_context(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    coding = ToolModule.objects.get(slug="coding_sessions")
    if CODING_GUIDANCE.strip() not in coding.caller_instructions:
        coding.caller_instructions = coding.caller_instructions.rstrip() + CODING_GUIDANCE
        coding.save(update_fields=["caller_instructions", "updated_at"])
    ssh = ToolModule.objects.get(slug="ssh_connections")
    if SSH_GUIDANCE.strip() not in ssh.caller_instructions:
        ssh.caller_instructions = ssh.caller_instructions.rstrip() + SSH_GUIDANCE
        ssh.save(update_fields=["caller_instructions", "updated_at"])

    delegate = ToolFunction.objects.get(manifest_id="coding_sessions.delegate_task")
    delegate.description = (
        "Send a specific instruction to an existing persistent Codex session for a small one-turn task; "
        "the saved thread, repository context, and working directory are retained."
    )
    delegate.params_schema = {
        "type": "object",
        "properties": {
            "session": {"type": "string", "description": "Coding session display name or UUID"},
            "task": {"type": "string", "description": "Exact task or command-like instruction to send to Codex"},
            "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 900},
        },
        "required": ["session", "task"],
    }
    delegate.examples = [
        {"user_prompt": "In my Corv coding session, run the tests and fix the small failure", "params": {"session": "Corv AI", "task": "Run the relevant tests, diagnose the failure, implement the small fix, and verify it."}},
        {"user_prompt": "Ask the open Codex session to check git status", "params": {"session": "Corv AI", "task": "Check git status and summarize the current changes."}},
    ]
    delegate.save(update_fields=["description", "params_schema", "examples", "updated_at"])

    command = ToolFunction.objects.get(manifest_id="ssh_connections.run_command")
    command.description = (
        "Run an exact bounded shell command directly on a saved SSH machine; prefer this for simple "
        "inspection or operational commands that do not require code reasoning or edits."
    )
    command.examples = [
        {"user_prompt": "Check disk space on Animus", "params": {"machine": "Animus Server", "command": "df -h", "session_name": "Corv"}},
        {"user_prompt": "Show whether nginx is running", "params": {"machine": "Animus Server", "command": "systemctl is-active nginx", "session_name": "Corv"}},
    ]
    command.save(update_fields=["description", "examples", "updated_at"])


def reverse_context(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0049_coding_activity_tool")]
    operations = [migrations.RunPython(update_routing_context, reverse_context)]
