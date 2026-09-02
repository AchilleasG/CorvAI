from django.db import migrations
GUIDANCE=" Every delegation spawned from a chat or call is tracked independently, including concurrent work. Use list_conversation_delegations to inspect them and set_conversation_delegation_wait to interrupt, resume, or switch a wait. Ask whether to wait before spawning unless already stated. Questions are always returned."
def configure(apps,schema_editor):
    Module=apps.get_model("orchestration","ToolModule"); Function=apps.get_model("orchestration","ToolFunction"); from orchestration.registry import FunctionRegistry
    module=Module.objects.get(slug="coding_sessions")
    if GUIDANCE.strip() not in module.caller_instructions: module.caller_instructions=module.caller_instructions.rstrip()+GUIDANCE; module.save(update_fields=["caller_instructions","updated_at"])
    for mid,name in [("coding_sessions.list_conversation_delegations","List Conversation Delegations"),("coding_sessions.set_conversation_delegation_wait","Set Delegation Wait Mode")]:
        r=FunctionRegistry.get(mid); Function.objects.update_or_create(manifest_id=mid,defaults={"module":module,"name":name,"description":r.description,"params_schema":r.params_schema,"return_schema":r.return_schema or {},"handler_ref":r.handler_ref,"tags":["coding","delegation","conversation"],"examples":[],"deprecated":False})
def reverse(apps,schema_editor): apps.get_model("orchestration","ToolFunction").objects.filter(manifest_id__in=["coding_sessions.list_conversation_delegations","coding_sessions.set_conversation_delegation_wait"]).delete()
class Migration(migrations.Migration):
    dependencies=[("orchestration","0055_durable_chat_delegation_wait"),("coding","0006_flexible_conversation_watches")]
    operations=[migrations.RunPython(configure,reverse)]
