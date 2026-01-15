from django.db import migrations


def seed_messages_module(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module, _ = ToolModule.objects.update_or_create(
        slug="messages",
        defaults={
            "name": "Messages",
            "description": "Send standalone inbox messages to the user.",
            "caller_instructions": (
                "Use messages.send_message to send a text update. "
                "Keep the title short and the body clear and actionable."
            ),
        },
    )

    ToolFunction.objects.update_or_create(
        manifest_id="messages.send_message",
        defaults={
            "module": module,
            "name": "messages.send_message",
            "description": "Send a standalone inbox message with a push notification.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "kind": {"type": "string", "description": "info|call_missed|call_text"},
                },
                "required": ["body"],
            },
            "return_schema": {"type": "object"},
            "deprecated": False,
            "handler_ref": "orchestration.tools.messages.send_message",
        },
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0027_call_sessions_module"),
    ]

    operations = [
        migrations.RunPython(seed_messages_module, noop),
    ]
