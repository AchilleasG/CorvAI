from django.db import migrations

GUIDANCE = " Absolute-time rule for note content: every temporal reference must be objective and absolute, never relative. Before add_note or update_note, replace today, tonight, tomorrow, yesterday, now, currently, this morning, next week, ago, 'in X days', and equivalent phrases with the exact calendar date and, when relevant and known, clock time plus timezone. Express durations using explicit start and end dates. If the user only says morning or night, preserve that label but attach its exact date; never invent a clock time. For a changing status, record the exact as-of date/time. Scan the final note content and remove every remaining relative temporal expression before writing it."

def configure(apps,schema_editor):
    Module=apps.get_model("orchestration","ToolModule"); Function=apps.get_model("orchestration","ToolFunction")
    module=Module.objects.get(slug="user_info")
    if GUIDANCE.strip() not in module.caller_instructions:
        module.caller_instructions=module.caller_instructions.rstrip()+GUIDANCE
        module.save(update_fields=["caller_instructions","updated_at"])
    descriptions={
        "user_info.add_note":"Note text. All temporal references must use exact calendar dates/times, never relative wording such as today, tomorrow, now, or in X days.",
        "user_info.update_note":"Updated content. Rewrite every temporal reference as an exact date/time; never persist relative wording such as today, tomorrow, now, or in X days.",
    }
    for manifest_id,description in descriptions.items():
        function=Function.objects.filter(manifest_id=manifest_id).first()
        if not function: continue
        schema=dict(function.params_schema); properties=dict(schema.get("properties",{})); content=dict(properties.get("content",{})); content["description"]=description; properties["content"]=content; schema["properties"]=properties; function.params_schema=schema; function.save(update_fields=["params_schema","updated_at"])

class Migration(migrations.Migration):
    dependencies=[("orchestration","0072_note_creation_quality_guidance")]
    operations=[migrations.RunPython(configure,migrations.RunPython.noop)]
