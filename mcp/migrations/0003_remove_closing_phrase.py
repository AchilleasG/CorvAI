from django.db import migrations


def forward(apps, schema_editor):
    Persona = apps.get_model('mcp', 'AssistantPersona')
    persona = Persona.objects.filter(slug='corv').first()
    if not persona:
        return
    guidelines = persona.style_guidelines or []
    persona.style_guidelines = [
        line for line in guidelines if "Corv out" not in line
    ]
    persona.closing_phrase = ""
    persona.save(update_fields=['style_guidelines', 'closing_phrase'])


def backward(apps, schema_editor):
    Persona = apps.get_model('mcp', 'AssistantPersona')
    persona = Persona.objects.filter(slug='corv').first()
    if not persona:
        return
    guidelines = persona.style_guidelines or []
    if "You must always end your responses with the phrase 'Corv out.'" not in guidelines:
        guidelines.append("You must always end your responses with the phrase 'Corv out.'")
    persona.style_guidelines = guidelines
    persona.closing_phrase = "Corv out."
    persona.save(update_fields=['style_guidelines', 'closing_phrase'])


class Migration(migrations.Migration):
    dependencies = [
        ('mcp', '0002_seed_initial_content'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
