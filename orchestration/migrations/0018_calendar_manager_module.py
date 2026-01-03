from django.db import migrations
import json


def seed_calendar_manager(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    module, _ = ToolModule.objects.update_or_create(
        slug="calendar_manager",
        defaults={
            "name": "Calendar Manager",
            "description": "Unified calendar surface combining hard (Google) and soft events.",
            "caller_instructions": (
                "Use calendar_manager.* for all scheduling. "
                "Use list_combined to fetch availability (hard + soft). "
                "Use create_soft_event for flexible tasks; promote_slot to lock them as hard events. "
                "Use replan_window to reschedule when user requests changes. "
                "Only use create_event when user explicitly wants a hard calendar entry."
            ),
        },
    )

    functions = [
        "calendar_manager.list_combined",
        "calendar_manager.create_soft_event",
        "calendar_manager.list_soft_events",
        "calendar_manager.promote_slot",
        "calendar_manager.replan_window",
        "calendar_manager.create_event",
        "calendar_manager.list_events",
    ]
    for manifest_id in functions:
        # Handler refs follow module + function name.
        handler_ref = manifest_id.replace("calendar_manager.", "orchestration.tools.calendar_manager.")
        ToolFunction.objects.update_or_create(
            manifest_id=manifest_id,
            defaults={
                "module": module,
                "name": manifest_id,
                "description": "",
                "params_schema": {},
                "return_schema": {},
                "deprecated": False,
                "handler_ref": handler_ref,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0017_update_list_soft_events_time_filters"),
    ]

    operations = [
        migrations.RunPython(seed_calendar_manager, noop),
    ]
