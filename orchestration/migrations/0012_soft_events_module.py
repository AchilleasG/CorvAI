from django.db import migrations


def seed_soft_events_module(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module, _ = ToolModule.objects.update_or_create(
        slug="soft_events",
        defaults={
            "name": "Soft Events",
            "description": "Flexible tasks Corv can schedule around hard calendar events.",
            "caller_instructions": (
                "Use soft_events.create_soft_event to capture flexible tasks with deadlines/frequency. "
                "Soft events can be planned into free time; avoid putting them on the calendar directly unless promoting."
            ),
        },
    )

    ToolFunction.objects.update_or_create(
        manifest_id="soft_events.create_soft_event",
        defaults={
            "module": module,
            "name": "soft_events.create_soft_event",
            "description": "Create a flexible soft event (task) that Corv can schedule.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "duration_minutes": {"type": "integer", "default": 30},
                    "soft_deadline": {"type": "string"},
                    "hard_deadline": {"type": "string"},
                    "frequency": {"type": "string"},
                    "preferred_dayparts": {"type": "array", "items": {"type": "string"}},
                    "deferral_limit": {"type": "integer", "default": 3},
                    "priority": {"type": "integer", "default": 0},
                    "chat_id": {"type": "string"},
                },
                "required": ["title"],
            },
            "return_schema": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "status": {"type": "string"}},
            },
            "deprecated": False,
            "handler_ref": "orchestration.tools.soft_events.create_soft_event",
        },
    )

    ToolFunction.objects.update_or_create(
        manifest_id="soft_events.list_soft_events",
        defaults={
            "module": module,
            "name": "soft_events.list_soft_events",
            "description": "List soft events.",
            "params_schema": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
            },
            "return_schema": {
                "type": "object",
                "properties": {
                    "events": {"type": "array", "items": {"type": "object"}},
                },
            },
            "deprecated": False,
            "handler_ref": "orchestration.tools.soft_events.list_soft_events",
        },
    )

    ToolFunction.objects.update_or_create(
        manifest_id="soft_events.list_slots",
        defaults={
            "module": module,
            "name": "soft_events.list_slots",
            "description": "List planned soft-event slots.",
            "params_schema": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
            },
            "return_schema": {
                "type": "object",
                "properties": {
                    "slots": {"type": "array", "items": {"type": "object"}},
                },
            },
            "deprecated": False,
            "handler_ref": "orchestration.tools.soft_events.list_slots",
        },
    )

    ToolFunction.objects.update_or_create(
        manifest_id="soft_events.promote_slot",
        defaults={
            "module": module,
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
    )

    ToolFunction.objects.update_or_create(
        manifest_id="soft_events.replan_window",
        defaults={
            "module": module,
            "name": "soft_events.replan_window",
            "description": "Manually trigger a replan of the soft events window.",
            "params_schema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "default": 14},
                    "note": {"type": "string"},
                },
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
    )


def noop_reverse(apps, schema_editor):
    # Keep module and function if rollback to avoid dangling data assumptions.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0011_softevent_softeventslot"),
    ]

    operations = [
        migrations.RunPython(seed_soft_events_module, noop_reverse),
    ]
