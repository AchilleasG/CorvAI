from django.db import migrations


CALENDAR_MANAGER_CALLER_INSTRUCTIONS = (
    "Use calendar_manager.* for scheduling workflows. "
    "Use list_combined to inspect hard events and current soft slots before planning changes. "
    "Create one soft event per intended session (not per entire topic). "
    "For flexible sessions, set preferred_duration_minutes and min_duration_minutes; min must be <= preferred. "
    "The planner may schedule any slot between min and preferred duration when availability is constrained. "
    "Use replan_window after creating or editing multiple soft events so slots are recalculated against availability and deadlines. "
    "Promote slots to hard events only when user asks to lock them in or risk is high."
)


def update_calendar_manager_guidance(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")

    ToolModule.objects.filter(slug="calendar_manager").update(
        caller_instructions=CALENDAR_MANAGER_CALLER_INSTRUCTIONS
    )

    create_params = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "notes": {"type": "string", "description": "Optional scheduling notes"},
            "preferred_duration_minutes": {
                "type": "integer",
                "default": 60,
                "description": "Preferred duration in minutes",
            },
            "min_duration_minutes": {
                "type": "integer",
                "default": 30,
                "description": "Minimum acceptable duration",
            },
            "soft_deadline": {
                "type": "string",
                "description": "ISO datetime deadline (soft)",
            },
            "hard_deadline": {
                "type": "string",
                "description": "ISO datetime deadline (hard)",
            },
            "frequency": {
                "type": "string",
                "description": "Optional recurrence description (e.g., weekly)",
            },
            "deferral_limit": {"type": "integer", "default": 3},
            "priority": {
                "type": "integer",
                "default": 0,
                "description": "Higher = more urgent",
            },
            "chat_id": {
                "type": "string",
                "description": "Optional chat id for context/notifications",
            },
        },
        "required": ["title"],
    }

    ToolFunction.objects.filter(
        manifest_id__in=[
            "calendar_manager.create_soft_event",
            "soft_events.create_soft_event",
        ]
    ).update(
        description=(
            "Create a flexible soft event session. "
            "Use preferred_duration_minutes as the ideal duration and "
            "min_duration_minutes as the acceptable lower bound."
        ),
        params_schema=create_params,
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0036_update_soft_event_create_params"),
    ]

    operations = [
        migrations.RunPython(update_calendar_manager_guidance, noop),
    ]
