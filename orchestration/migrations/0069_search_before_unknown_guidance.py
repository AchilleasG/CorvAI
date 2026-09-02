from django.db import migrations

PERSONAL = " Search-before-unknown rule: never say or imply that personal information is unknown, unavailable, or not remembered before calling user_info.search_knowledge. This unified semantic search covers generic notes, people, locations, tags, and future note types. If the request might be personal, search here first; only report no answer after the search returns none or fails."
GENERAL = " Search-before-unknown rule: never say or imply that general, public, uncertain, or current information is unknown before calling internet_search.search. If a question might concern the user's private context, search user_info.search_knowledge first, then use internet search if needed. Only report no answer after the relevant searches return none or fail."

def configure(apps,schema_editor):
    Module=apps.get_model("orchestration","ToolModule")
    for slug,guidance in (("user_info",PERSONAL),("internet_search",GENERAL)):
        module=Module.objects.get(slug=slug)
        if guidance.strip() not in module.caller_instructions:
            module.caller_instructions=module.caller_instructions.rstrip()+guidance
            module.save(update_fields=["caller_instructions","updated_at"])

class Migration(migrations.Migration):
    dependencies=[("orchestration","0068_structured_knowledge_actions")]
    operations=[migrations.RunPython(configure,migrations.RunPython.noop)]
