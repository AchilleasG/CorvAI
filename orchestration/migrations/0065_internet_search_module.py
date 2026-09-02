from django.db import migrations


MODULE = {
    "name": "Internet Search",
    "description": "Search the public internet for current or uncertain general knowledge.",
    "tags": ["search", "internet", "knowledge"],
    "caller_instructions": (
        "Use internet_search.search when general knowledge is uncertain or could have changed, or when "
        "the user asks to search, verify, look up, or find public online information. Prefer specific "
        "Corv modules for private/user data. Preserve useful source URLs in the final response."
    ),
}
PARAMS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "A focused public-web research question."},
        "context": {"type": "string", "description": "Optional location, date, or comparison constraints."},
    },
    "required": ["query"],
    "additionalProperties": False,
}


def add_search(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    module, _ = ToolModule.objects.update_or_create(slug="internet_search", defaults=MODULE)
    ToolFunction.objects.update_or_create(
        manifest_id="internet_search.search",
        defaults={
            "module": module,
            "name": "Search the internet",
            "description": (
                "Search the public internet with an LLM and return a concise answer plus source URLs. "
                "Use for uncertain or current general knowledge and explicit lookup requests."
            ),
            "params_schema": PARAMS,
            "return_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}, "sources": {"type": "array"}},
            },
            "handler_ref": "orchestration.tools.internet_search.search",
            "tags": ["search", "internet", "knowledge"],
            "deprecated": False,
        },
    )


def remove_search(apps, schema_editor):
    apps.get_model("orchestration", "ToolFunction").objects.filter(
        manifest_id="internet_search.search"
    ).delete()
    apps.get_model("orchestration", "ToolModule").objects.filter(slug="internet_search").delete()


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0064_note_source_provenance")]
    operations = [migrations.RunPython(add_search, remove_search)]
