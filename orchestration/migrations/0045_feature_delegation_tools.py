from django.db import migrations


MODULE_DEFAULTS = {
    "name": "Coding sessions",
    "description": "Persistent full-access Codex sessions and autonomous feature delegations on saved SSH machines.",
    "caller_instructions": (
        "Use delegate_feature for substantial work with explicit acceptance criteria. Ask whether independent QA "
        "should be enabled unless the user already said; pass that choice as qa_enabled. The delegation automatically "
        "continues through coder, independent QA, and fix cycles. Do not ask the user to say Resume while it is coding, "
        "testing, or fixing. Use get_feature_delegation for status. Only relay a question when status is needs_input, "
        "then pass the user's answer to resume_feature_delegation. Coding session display names are accepted directly; "
        "do not ask the user for a UUID after list_sessions found an unambiguous name. Use delegate_task for small one-turn changes."
    ),
}


DEFINITIONS = [
    (
        "coding_sessions.delegate_feature",
        "Start durable coding with optional independent browser-capable QA and automatic fix cycles.",
        {"type": "object", "properties": {"session": {"type": "string", "description": "Coding session display name or UUID; an unambiguous display name is accepted directly"}, "title": {"type": "string"}, "description": {"type": "string"}, "acceptance_criteria": {"type": "array", "items": {"type": "string"}}, "qa_enabled": {"type": "boolean"}, "max_iterations": {"type": "integer", "minimum": 1, "maximum": 12}}, "required": ["session", "title", "description", "acceptance_criteria", "qa_enabled"]},
    ),
    ("coding_sessions.list_feature_delegations", "List feature delegations.", {"type": "object", "properties": {"session": {"type": "string"}}}),
    ("coding_sessions.get_feature_delegation", "Get feature implementation and QA progress.", {"type": "object", "properties": {"delegation": {"type": "string"}}, "required": ["delegation"]}),
    ("coding_sessions.resume_feature_delegation", "Resume a feature after a user decision or interruption.", {"type": "object", "properties": {"delegation": {"type": "string"}, "decision": {"type": "string"}}, "required": ["delegation"]}),
    ("coding_sessions.stop_feature_delegation", "Stop a feature delegation.", {"type": "object", "properties": {"delegation": {"type": "string"}}, "required": ["delegation"]}),
]


def add_feature_tools(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    module, _ = ToolModule.objects.update_or_create(slug="coding_sessions", defaults=MODULE_DEFAULTS)
    for manifest_id, description, params in DEFINITIONS:
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


def remove_feature_tools(apps, schema_editor):
    apps.get_model("orchestration", "ToolFunction").objects.filter(
        manifest_id__in=[item[0] for item in DEFINITIONS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("coding", "0002_feature_delegations"),
        ("orchestration", "0044_coding_sessions_module"),
    ]
    operations = [migrations.RunPython(add_feature_tools, remove_feature_tools)]
