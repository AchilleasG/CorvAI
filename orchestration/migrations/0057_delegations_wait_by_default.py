from django.db import migrations

GUIDANCE = (
    " Waiting is now the default for every new chat or call delegation and this supersedes earlier "
    "instructions to ask first. Do not ask whether to wait. Omit wait_for_completion or pass true unless "
    "the user explicitly asks to start without waiting. The user can interrupt, resume, or switch any "
    "tracked wait later, and multiple delegations remain independently tracked."
)

def configure(apps, schema_editor):
    Module=apps.get_model("orchestration","ToolModule"); Function=apps.get_model("orchestration","ToolFunction")
    module=Module.objects.get(slug="coding_sessions")
    module.caller_instructions=module.caller_instructions.rstrip()+GUIDANCE
    module.save(update_fields=["caller_instructions","updated_at"])
    for mid in ["coding_sessions.delegate_task","coding_sessions.delegate_feature"]:
        tool=Function.objects.get(manifest_id=mid); schema=tool.params_schema or {"type":"object","properties":{}}
        schema.setdefault("properties",{})["wait_for_completion"]={"type":"boolean","default":True,"description":"Defaults to true; set false only when the user explicitly asks not to wait"}
        tool.params_schema=schema; tool.save(update_fields=["params_schema","updated_at"])

class Migration(migrations.Migration):
    dependencies=[("orchestration","0056_flexible_call_and_chat_waits")]
    operations=[migrations.RunPython(configure,migrations.RunPython.noop)]
