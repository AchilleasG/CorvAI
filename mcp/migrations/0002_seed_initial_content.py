from django.db import migrations

def seed_forward(apps, schema_editor):
    Persona = apps.get_model('mcp', 'AssistantPersona')
    Profile = apps.get_model('mcp', 'PersonaUserProfile')
    Module = apps.get_model('mcp', 'MCPModule')
    Function = apps.get_model('mcp', 'ModuleFunction')
    Parameter = apps.get_model('mcp', 'ModuleFunctionParameter')
    ErrorPolicy = apps.get_model('mcp', 'ModuleFunctionErrorPolicy')

    persona, _ = Persona.objects.get_or_create(
        slug='corv',
        defaults={
            'name': 'Corv',
            'mission': 'Be the pragmatic AI operations partner who anticipates blockers and keeps delivery grounded.',
            'system_prompt': (
                "You are Corv, the resident operations co-pilot for lean engineering teams. Think like a calm chief of staff who pairs strategic awareness with tactical execution. Keep answers grounded, cite assumptions when details are missing, and always close with the most leverage-rich action items. You enjoy being concise, structured, and direct while still sounding human."
            ),
            'style_guidelines': [
                'Clarify the objective before diving into solutions when requirements feel vague.',
                'Favor bullet points or short numbered lists for plans and summaries.',
                "Highlight risks, dependencies, and metrics owners might forget to track.",
                'Suggest one bold or creative lever when it can unlock outsized impact.',
                "Never fabricate data or status; surface uncertainties explicitly.",
                "You must always end your responses with the phrase 'Corv out.'",
            ],
            'closing_phrase': 'Corv out.',
        },
    )

    Profile.objects.get_or_create(
        persona=persona,
        profile_id='default',
        defaults={
            'name': 'Rae Morales',
            'role': 'Product-minded engineering lead scaling an AI platform',
            'summary': 'Rae is an impatient builder juggling roadmap triage, stakeholder updates, and hiring needs while keeping delivery grounded in data.',
            'goals': [
                'Ship a stable Corv assistant experience that feels proactive, not reactive.',
                'Keep exec updates crisp with measurable progress signals.',
                'Surface risks early so the team is never surprised.',
            ],
            'preferences': [
                'Appreciates honest trade-offs instead of happy-path answers.',
                'Wants action items bucketed by owner or function.',
                'Needs assumptions called out when information is thin.',
            ],
            'is_default': True,
        },
    )

    calendar_module, _ = Module.objects.get_or_create(
        slug='calendar',
        defaults={
            'name': 'Calendar',
            'description': 'Scheduling, availability checks, and event orchestration.',
        },
    )

    add_event_fn, _ = Function.objects.get_or_create(
        module=calendar_module,
        slug='add_event',
        defaults={
            'name': 'Add Calendar Event',
            'description': 'Create a calendar entry for a meeting, reminder, or appointment.',
            'knowledge_requirements': [
                'Event title or intent (e.g., doctor appointment).',
                'Event date in ISO or natural language form that can be resolved.',
                'Start time and optional end time.',
                'Target calendar or attendee context.'
            ],
            'result_description': 'Adds the event and returns the scheduled time block.',
        },
    )

    params = [
        ('title', 'string', True, 'Human readable name for the event.', ''),
        ('date', 'date', True, 'Calendar date (YYYY-MM-DD).', ''),
        ('time', 'time', True, 'Start time in 24h HH:MM.', ''),
        ('duration_minutes', 'integer', False, 'Length of the event.', '60'),
        ('notes', 'string', False, 'Additional context or instructions.', ''),
    ]

    for name, data_type, required, description, default in params:
        Parameter.objects.get_or_create(
            function=add_event_fn,
            name=name,
            defaults={
                'data_type': data_type,
                'description': description,
                'required': required,
                'default_value': default,
            },
        )

    ErrorPolicy.objects.get_or_create(
        function=add_event_fn,
        code='EVENT_CONFLICT',
        defaults={
            'description': 'There is already an event on the calendar for that slot.',
            'handling_notes': 'Offer to reschedule, overwrite, or skip scheduling for now.',
            'severity': 'warn',
        },
    )


def seed_backward(apps, schema_editor):
    Persona = apps.get_model('mcp', 'AssistantPersona')
    Persona.objects.filter(slug='corv').delete()

    Module = apps.get_model('mcp', 'MCPModule')
    Module.objects.filter(slug='calendar').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('mcp', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_forward, seed_backward),
    ]
