from django.db import migrations

GUIDANCE = " Before creating or updating any note, always run a broad semantic user_info.search_knowledge query for its subject and related facts first. Read the relevant results in context to avoid duplicates and reuse the existing tag vocabulary where appropriate; do not apply deterministic filters unless the user explicitly requested them. Write time-stable facts whenever possible: convert relative timing such as 'in X days' to the exact calendar date/time, and store birth date or birth year rather than current age. Never save a value that becomes false merely as time passes when an invariant fact is available. If the changing value itself matters, include an explicit as-of date or expires_at."
ADD_DESCRIPTION = "Add a permanent or timed generic note after semantically searching relevant knowledge first. Reuse established tags and store stable dates/birth years instead of relative or changing values."
UPDATE_DESCRIPTION = "Update a generic note after semantically searching related knowledge first. Keep tags consistent and express facts in a time-stable form."

def configure(apps,schema_editor):
    Module=apps.get_model("orchestration","ToolModule"); Function=apps.get_model("orchestration","ToolFunction")
    module=Module.objects.get(slug="user_info")
    if GUIDANCE.strip() not in module.caller_instructions:
        module.caller_instructions=module.caller_instructions.rstrip()+GUIDANCE
        module.save(update_fields=["caller_instructions","updated_at"])
    Function.objects.filter(manifest_id="user_info.add_note").update(description=ADD_DESCRIPTION)
    Function.objects.filter(manifest_id="user_info.update_note").update(description=UPDATE_DESCRIPTION)

class Migration(migrations.Migration):
    dependencies=[("orchestration","0071_timed_notes")]
    operations=[migrations.RunPython(configure,migrations.RunPython.noop)]
