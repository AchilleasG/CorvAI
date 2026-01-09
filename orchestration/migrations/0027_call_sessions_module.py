from django.db import migrations


def seed_call_sessions(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module, _ = ToolModule.objects.update_or_create(
        slug="call_sessions",
        defaults={
            "name": "Call Sessions",
            "description": "Create and manage in-app call sessions and inbox messages.",
            "caller_instructions": (
                "Use call_sessions.create_session to place calls, optionally scheduled. "
                "If a user agrees to do something, schedule a confirmation call about 10 minutes "
                "after the estimated completion time if you can infer it. "
                "Use call_sessions.send_message to send a text if a call is missed or declined."
            ),
        },
    )

    functions = {
        "call_sessions.create_session": {
            "description": "Create a call session with a goal; can be immediate or scheduled.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "scheduled_for": {"type": "string", "description": "ISO datetime for scheduled call"},
                },
                "required": ["goal"],
            },
            "return_schema": {"type": "object"},
        },
        "call_sessions.list_sessions": {
            "description": "List call sessions with optional status filter.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "scheduled|ringing|in_call|missed|completed|canceled"},
                },
            },
            "return_schema": {"type": "object"},
        },
        "call_sessions.update_session": {
            "description": "Update a call session status.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "status": {"type": "string", "description": "scheduled|ringing|in_call|missed|completed|canceled"},
                },
                "required": ["session_id", "status"],
            },
            "return_schema": {"type": "object"},
        },
        "call_sessions.send_message": {
            "description": "Send a standalone user message to the inbox.",
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
        },
    }
    for manifest_id, payload in functions.items():
        handler_ref = manifest_id.replace("call_sessions.", "orchestration.tools.call_sessions.")
        ToolFunction.objects.update_or_create(
            manifest_id=manifest_id,
            defaults={
                "module": module,
                "name": manifest_id,
                "description": payload["description"],
                "params_schema": payload["params_schema"],
                "return_schema": payload["return_schema"],
                "deprecated": False,
                "handler_ref": handler_ref,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0026_call_sessions_and_inbox"),
    ]

    operations = [
        migrations.RunPython(seed_call_sessions, noop),
    ]
