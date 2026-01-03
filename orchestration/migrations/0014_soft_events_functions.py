from django.db import migrations


def seed_soft_event_functions(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    try:
        module = ToolModule.objects.get(slug="soft_events")
    except ToolModule.DoesNotExist:
        return

    funcs = [
        (
            "soft_events.list_soft_events",
            {
                "name": "soft_events.list_soft_events",
                "description": "List soft events.",
                "params_schema": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                },
                "return_schema": {
                    "type": "object",
                    "properties": {"events": {"type": "array", "items": {"type": "object"}}},
                },
                "deprecated": False,
                "handler_ref": "orchestration.tools.soft_events.list_soft_events",
            },
        ),
        (
            "soft_events.list_slots",
            {
                "name": "soft_events.list_slots",
                "description": "List planned soft-event slots.",
                "params_schema": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                },
                "return_schema": {
                    "type": "object",
                    "properties": {"slots": {"type": "array", "items": {"type": "object"}}},
                },
                "deprecated": False,
                "handler_ref": "orchestration.tools.soft_events.list_slots",
            },
        ),
        (
            "soft_events.promote_slot",
            {
                "name": "soft_events.promote_slot",
                "description": "Promote a soft-event slot to a calendar event.",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        "slot_id": {"type": "string"},
                        "summary": {"type": "string"},
                        "description": {"type": "string"},
                        "calendar_id": {"type": "string"},
                        "timezone": {"type": "string"},
                    },
                    "required": ["slot_id"],
                },
                "return_schema": {
                    "type": "object",
                    "properties": {"updated": {"type": "integer"}},
                },
                "deprecated": False,
                "handler_ref": "orchestration.tools.soft_events.promote_slot",
            },
        ),
        (
            "soft_events.replan_window",
            {
                "name": "soft_events.replan_window",
                "description": "Manually trigger a replan of the soft events window.",
                "params_schema": {
                    "type": "object",
                    "properties": {"days": {"type": "integer", "default": 14}, "note": {"type": "string"}},
                },
                "return_schema": {
                    "type": "object",
                    "properties": {
                        "actions": {"type": "integer"},
                        "created": {"type": "integer"},
                        "updated": {"type": "integer"},
                        "trace_id": {"type": "string"},
                    },
                },
                "deprecated": False,
                "handler_ref": "orchestration.tools.soft_events.replan_window",
            },
        ),
    ]

    for manifest_id, defaults in funcs:
        ToolFunction.objects.update_or_create(
            manifest_id=manifest_id,
            defaults={"module": module, **defaults},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0013_rename_orchestrati_key_5f2c2b_idx_orchestrati_key_5b0ae4_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_soft_event_functions, noop),
    ]
