from django.db import migrations


def update_ssh_tools(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    ToolModule.objects.filter(slug="ssh_connections").update(
        description="Connect to saved SSH machines and work in persistent remote shell sessions.",
        caller_instructions=(
            "Use only saved machines. List machines before choosing one when the target is ambiguous. "
            "Never request or expose passwords or private keys in chat. AI commands only work on machines "
            "whose owner explicitly enabled allow_ai_commands. Explain potentially destructive, privileged, "
            "or service-impacting commands and ask the user for confirmation before running them. Use a stable "
            "session_name for related commands so shell state such as the working directory and environment persists."
        ),
    )
    ToolFunction.objects.filter(manifest_id="ssh_connections.run_command").update(
        description="Run a command in a named persistent shell session on a saved SSH machine.",
        params_schema={
            "type": "object",
            "properties": {
                "machine": {"type": "string", "description": "Saved machine name or UUID"},
                "command": {"type": "string"},
                "session_name": {"type": "string", "description": "Persistent shell name; defaults to Corv"},
                "timeout_seconds": {"type": "integer"},
            },
            "required": ["machine", "command"],
        },
    )


class Migration(migrations.Migration):
    dependencies = [("ssh_connections", "0001_initial")]
    operations = [migrations.RunPython(update_ssh_tools, migrations.RunPython.noop)]
