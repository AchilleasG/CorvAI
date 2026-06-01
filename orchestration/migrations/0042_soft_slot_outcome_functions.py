from django.db import migrations


def seed_soft_slot_outcome_functions(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    function_defs = [
        (
            "soft_events",
            "soft_events.mark_slot_outcome",
            "Mark a planned soft-event session as completed or not performed and optionally log why.",
            "orchestration.tools.soft_events.mark_slot_outcome",
        ),
        (
            "calendar_manager",
            "calendar_manager.mark_slot_outcome",
            "Mark a planned soft-event session as completed or not performed and record why.",
            "orchestration.tools.calendar_manager.mark_slot_outcome",
        ),
    ]

    params_schema = {
        "type": "object",
        "properties": {
            "slot_id": {"type": "string"},
            "outcome": {"type": "string", "description": "completed or not_performed"},
            "reason": {"type": "string"},
            "minutes_spent": {"type": "integer"},
            "completed_task_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["slot_id", "outcome"],
    }

    for module_slug, manifest_id, description, handler_ref in function_defs:
        module = ToolModule.objects.filter(slug=module_slug).first()
        if module is None:
            continue
        ToolFunction.objects.update_or_create(
            manifest_id=manifest_id,
            defaults={
                "module": module,
                "name": manifest_id,
                "description": description,
                "params_schema": params_schema,
                "return_schema": {"type": "object"},
                "deprecated": False,
                "handler_ref": handler_ref,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0041_objectives_module"),
    ]

    operations = [
        migrations.RunPython(seed_soft_slot_outcome_functions, noop),
    ]
