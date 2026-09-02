from django.db import migrations

GUIDANCE = " Semantic-first retrieval rule: use user_info.search_knowledge with the user's natural-language query and normally limit=10. Do not invent or infer tags, source, entity type, user_id, or other deterministic filters. Filters are hard exclusions, not relevance hints; pass them only when the user explicitly asks for that exact constraint. Return the most relevant result payloads into context. If an explicitly requested filtered search is empty, retry without filters before concluding the knowledge is absent."
DESCRIPTION = "Preferred personal-memory retrieval: broad semantic search across generic notes, locations, people, and future note types. Use the natural-language query without deterministic filters unless the user explicitly requests a constraint. Returns top-ranked payloads for reasoning and prioritizes likely entity classes before broadening."
SCHEMA = {"type":"object","properties":{"query":{"type":"string","description":"Natural-language semantic query"},"tags":{"type":"array","items":{"type":"string"},"description":"Hard tag filter; omit unless the user explicitly requested these tags"},"limit":{"type":"integer","default":10,"description":"Number of top relevant payloads to fetch into context; normally 10"}},"required":["query"]}

def configure(apps,schema_editor):
    Module=apps.get_model("orchestration","ToolModule");Function=apps.get_model("orchestration","ToolFunction")
    module=Module.objects.get(slug="user_info")
    if GUIDANCE.strip() not in module.caller_instructions:
        module.caller_instructions=module.caller_instructions.rstrip()+GUIDANCE
        module.save(update_fields=["caller_instructions","updated_at"])
    function=Function.objects.get(manifest_id="user_info.search_knowledge")
    function.description=DESCRIPTION;function.params_schema=SCHEMA
    function.save(update_fields=["description","params_schema","updated_at"])

class Migration(migrations.Migration):
    dependencies=[("orchestration","0069_search_before_unknown_guidance")]
    operations=[migrations.RunPython(configure,migrations.RunPython.noop)]
