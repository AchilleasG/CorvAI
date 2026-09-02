from django.db import migrations

GUIDANCE=" Presentation by channel: in text chat, use polished GitHub-flavored Markdown when it improves scanning: short descriptive headings for multi-part answers, compact bullets for distinct items, bold only for useful labels, and descriptive clickable links for sources. Keep simple answers simple and avoid decorative over-formatting. In calls and spoken output, never speak Markdown syntax, headings, bullets, or link notation; use short natural sentences."

def configure(apps,schema_editor):
    Persona=apps.get_model("orchestration","FrontmanPersona")
    for persona in Persona.objects.all():
        if GUIDANCE.strip() not in persona.postamble:
            persona.postamble=persona.postamble.rstrip()+GUIDANCE
            persona.save(update_fields=["postamble","updated_at"])

class Migration(migrations.Migration):
    dependencies=[("orchestration","0074_scheduler_delivery_reliability")]
    operations=[migrations.RunPython(configure,migrations.RunPython.noop)]
