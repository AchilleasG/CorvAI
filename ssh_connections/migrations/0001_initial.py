import uuid

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


def seed_ssh_module(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    module, _ = ToolModule.objects.update_or_create(
        slug="ssh_connections",
        defaults={
            "name": "SSH Connections",
            "description": "Connect to saved SSH machines and run remote shell commands.",
            "caller_instructions": (
                "Use only saved machines. List machines before choosing one when the target is ambiguous. "
                "Never request or expose passwords or private keys in chat. AI commands only work on machines "
                "whose owner explicitly enabled allow_ai_commands. Explain potentially destructive, privileged, "
                "or service-impacting commands and ask the user for confirmation before running them. Keep the "
                "connection open for follow-up commands unless the user asks to disconnect."
            ),
        },
    )
    functions = {
        "ssh_connections.list_machines": (
            "List saved SSH machines and their live connection state.",
            {"type": "object", "properties": {}},
        ),
        "ssh_connections.connect": (
            "Open and retain an SSH connection to a saved machine.",
            {"type": "object", "properties": {"machine": {"type": "string"}}, "required": ["machine"]},
        ),
        "ssh_connections.disconnect": (
            "Close the retained SSH connection to a saved machine.",
            {"type": "object", "properties": {"machine": {"type": "string"}}, "required": ["machine"]},
        ),
        "ssh_connections.run_command": (
            "Run a shell command on a saved machine. The connection is reused and remains open.",
            {
                "type": "object",
                "properties": {
                    "machine": {"type": "string", "description": "Saved machine name or UUID"},
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                },
                "required": ["machine", "command"],
            },
        ),
    }
    for manifest_id, (description, params_schema) in functions.items():
        ToolFunction.objects.update_or_create(
            manifest_id=manifest_id,
            defaults={
                "module": module,
                "name": manifest_id,
                "description": description,
                "params_schema": params_schema,
                "return_schema": {"type": "object"},
                "deprecated": False,
                "handler_ref": manifest_id.replace("ssh_connections.", "orchestration.tools.ssh_connections."),
            },
        )


class Migration(migrations.Migration):
    initial = True
    dependencies = [("orchestration", "0043_hardeventtasklink")]
    operations = [
        migrations.CreateModel(
            name="SshMachine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120, unique=True)),
                ("host", models.CharField(max_length=255)),
                ("port", models.PositiveIntegerField(default=22, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(65535)])),
                ("username", models.CharField(max_length=255)),
                ("auth_type", models.CharField(choices=[("password", "Password"), ("private_key", "Private key"), ("agent", "SSH agent")], default="private_key", max_length=24)),
                ("credential_encrypted", models.TextField(blank=True, default="")),
                ("host_key_fingerprint", models.CharField(blank=True, default="", max_length=128)),
                ("allow_ai_commands", models.BooleanField(default=False)),
                ("connect_timeout_seconds", models.PositiveIntegerField(default=15)),
                ("command_timeout_seconds", models.PositiveIntegerField(default=120)),
                ("keepalive_seconds", models.PositiveIntegerField(default=30)),
                ("notes", models.TextField(blank=True, default="")),
                ("last_connected_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name"], "indexes": [models.Index(fields=["name"], name="ssh_connect_name_d3d0a2_idx"), models.Index(fields=["host", "port"], name="ssh_connect_host_9fbf05_idx")]},
        ),
        migrations.CreateModel(
            name="SshCommandRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("command", models.TextField()),
                ("source", models.CharField(choices=[("api", "API"), ("assistant", "Assistant")], default="api", max_length=24)),
                ("exit_status", models.IntegerField(blank=True, null=True)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("succeeded", models.BooleanField(default=False)),
                ("error_summary", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("machine", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="command_records", to="ssh_connections.sshmachine")),
            ],
            options={"ordering": ["-created_at"], "indexes": [models.Index(fields=["machine", "created_at"], name="ssh_connect_machine_b7c627_idx")]},
        ),
        migrations.RunPython(seed_ssh_module, migrations.RunPython.noop),
    ]
