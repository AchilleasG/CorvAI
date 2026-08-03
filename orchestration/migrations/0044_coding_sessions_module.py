from django.db import migrations


MODULE_DEFAULTS = {
    "name": "Coding sessions",
    "description": "Persistent full-access Codex sessions that work on saved SSH machines.",
    "caller_instructions": (
        "Use this module when the user asks Corv to perform coding work through Codex. "
        "Create or select a session, delegate the task, and report that it started. "
        "Use get_session when the user asks for progress. If status is needs_input, relay "
        "the question and options without guessing; pass the user's answer with answer_decision."
    ),
}


def add_coding_module(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    module, _ = ToolModule.objects.update_or_create(
        slug="coding_sessions",
        defaults=MODULE_DEFAULTS,
    )
    definitions = [
        ("coding_sessions.list_sessions", "List coding sessions.", {}),
        (
            "coding_sessions.create_session",
            "Create a persistent Codex coding session on an SSH machine.",
            {"type": "object", "properties": {"name": {"type": "string"}, "machine": {"type": "string"}, "remote_working_directory": {"type": "string"}}, "required": ["name", "machine", "remote_working_directory"]},
        ),
        (
            "coding_sessions.delegate_task",
            "Start a coding task in a persistent Codex session.",
            {"type": "object", "properties": {"session": {"type": "string"}, "task": {"type": "string"}, "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 900}}, "required": ["session", "task"]},
        ),
        (
            "coding_sessions.get_session",
            "Get coding results, errors, or a pending decision.",
            {"type": "object", "properties": {"session": {"type": "string"}}, "required": ["session"]},
        ),
        (
            "coding_sessions.answer_decision",
            "Give Codex the user's answer to a pending decision.",
            {"type": "object", "properties": {"session": {"type": "string"}, "decision": {"type": "string"}, "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 900}}, "required": ["session", "decision"]},
        ),
        (
            "coding_sessions.stop_session",
            "Explicitly stop a persistent coding session.",
            {"type": "object", "properties": {"session": {"type": "string"}}, "required": ["session"]},
        ),
    ]
    for manifest_id, description, params in definitions:
        ToolFunction.objects.update_or_create(
            manifest_id=manifest_id,
            defaults={
                "module": module,
                "name": manifest_id.rsplit(".", 1)[-1].replace("_", " ").title(),
                "description": description,
                "handler_ref": manifest_id.replace("coding_sessions.", "orchestration.tools.coding_sessions."),
                "params_schema": params,
                "return_schema": {},
                "deprecated": False,
            },
        )


def remove_coding_module(apps, schema_editor):
    apps.get_model("orchestration", "ToolModule").objects.filter(slug="coding_sessions").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("coding", "0001_initial"),
        ("orchestration", "0043_hardeventtasklink"),
    ]
    operations = [migrations.RunPython(add_coding_module, remove_coding_module)]
