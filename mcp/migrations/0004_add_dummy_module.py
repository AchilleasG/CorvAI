from django.db import migrations

def forward(apps, schema_editor):
    Module = apps.get_model('mcp', 'MCPModule')
    Function = apps.get_model('mcp', 'ModuleFunction')
    Parameter = apps.get_model('mcp', 'ModuleFunctionParameter')
    ErrorPolicy = apps.get_model('mcp', 'ModuleFunctionErrorPolicy')

    module, _ = Module.objects.get_or_create(
        slug='dummy_ops',
        defaults={
            'name': 'Dummy Ops',
            'description': 'Playground module used for validating orchestration flows.',
        },
    )

    function, _ = Function.objects.get_or_create(
        module=module,
        slug='check_name',
        defaults={
            'name': 'Check Name',
            'description': 'Validates a provided name. Names starting with A are rejected.',
            'knowledge_requirements': ['A single name string supplied by the user.'],
            'result_description': 'Returns acknowledgement when the supplied name passes validation.',
        },
    )

    Parameter.objects.get_or_create(
        function=function,
        name='name',
        defaults={
            'data_type': 'string',
            'description': 'Name to validate. Cannot begin with the letter A.',
            'required': True,
        },
    )

    ErrorPolicy.objects.get_or_create(
        function=function,
        code='NAME_INVALID',
        defaults={
            'description': 'The provided name is not allowed.',
            'handling_notes': 'Let the user know names starting with A are blocked and ask for a different name.',
            'severity': 'warn',
        },
    )


def backward(apps, schema_editor):
    Module = apps.get_model('mcp', 'MCPModule')
    Module.objects.filter(slug='dummy_ops').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('mcp', '0003_remove_closing_phrase'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
