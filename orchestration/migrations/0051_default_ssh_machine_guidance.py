from django.db import migrations


GUIDANCE = (
    " The user can mark one command-enabled SSH machine as the default. Prefer the default machine "
    "when a safe command would materially improve answer quality, including calculations, data "
    "processing, format conversion, file generation, or bounded inspection. The machine argument "
    "may be omitted to select that default automatically. Do not run commands merely for ceremony, "
    "and continue to respect allow_ai_commands and destructive-action safeguards."
)


def add_default_machine_guidance(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    ssh = ToolModule.objects.get(slug="ssh_connections")
    if GUIDANCE.strip() not in ssh.caller_instructions:
        ssh.caller_instructions = ssh.caller_instructions.rstrip() + GUIDANCE
        ssh.save(update_fields=["caller_instructions", "updated_at"])

    coding = ToolModule.objects.get(slug="coding_sessions")
    coding_guidance = (
        " When creating a coding session for machine-independent work, omit the machine to use the "
        "user's default SSH machine."
    )
    if coding_guidance.strip() not in coding.caller_instructions:
        coding.caller_instructions = coding.caller_instructions.rstrip() + coding_guidance
        coding.save(update_fields=["caller_instructions", "updated_at"])

    command = ToolFunction.objects.get(manifest_id="ssh_connections.run_command")
    command.description = (
        "Run an exact bounded shell command on a saved SSH machine. Omit machine to use the user's default; "
        "use it when a safe calculation, conversion, file operation, or inspection improves the answer."
    )
    command.params_schema = {
        "type": "object",
        "properties": {
            "machine": {"type": "string", "description": "Saved machine name/id; omit for the default"},
            "command": {"type": "string", "description": "Exact shell command to execute"},
            "session_name": {"type": "string", "description": "Persistent shell name; defaults to Corv"},
            "timeout_seconds": {"type": "integer"},
        },
        "required": ["command"],
    }
    command.examples = [
        {"user_prompt": "Calculate the first 100 primes", "params": {"command": "python3 - <<'PY'\nimport sympy\nprint(list(sympy.primerange(1, 550))[:100])\nPY"}},
        {"user_prompt": "Convert these values to CSV on my usual machine", "params": {"command": "python3 -c 'print(\"value\\n1\\n2\")'"}},
    ]
    command.save(update_fields=["description", "params_schema", "examples", "updated_at"])

    create = ToolFunction.objects.get(manifest_id="coding_sessions.create_session")
    create.description = "Create a persistent Codex session; omit machine to use the user's default SSH machine."
    schema = create.params_schema or {}
    required = [value for value in schema.get("required", []) if value != "machine"]
    properties = schema.get("properties", {})
    if "machine" in properties:
        properties["machine"]["description"] = "Saved machine name/id; omit for the default"
    schema["required"] = required
    schema["properties"] = properties
    create.params_schema = schema
    create.save(update_fields=["description", "params_schema", "updated_at"])


def reverse_default_machine_guidance(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0050_codex_and_ssh_routing_context")]
    operations = [migrations.RunPython(add_default_machine_guidance, reverse_default_machine_guidance)]
