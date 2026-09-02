from django.db import migrations, models

GUIDANCE = " Timed notes: for temporary facts, reminders, access details, or information the user says is only valid until a date, create a normal generic note with expires_at set to an ISO 8601 date/time. Leave expires_at empty for permanent knowledge. Timed notes participate in ordinary semantic search until expiry, then are excluded from recall and safely soft-deleted automatically. Tell the user the expiry when creating or changing a timed note."

def configure(apps, schema_editor):
    Module=apps.get_model("orchestration","ToolModule"); Function=apps.get_model("orchestration","ToolFunction")
    module=Module.objects.get(slug="user_info")
    if GUIDANCE.strip() not in module.caller_instructions:
        module.caller_instructions=module.caller_instructions.rstrip()+GUIDANCE
        module.save(update_fields=["caller_instructions","updated_at"])
    add=Function.objects.filter(manifest_id="user_info.add_note").first()
    if add:
        add.description="Add a permanent or timed generic note with semantic-search embedding. Set expires_at only for knowledge that should stop being recalled after a specific time."
        schema=dict(add.params_schema); props=dict(schema.get("properties",{})); props["expires_at"]={"type":"string","description":"Optional ISO 8601 expiry date/time. After this time the note is excluded from recall and safely cleaned up."}; schema["properties"]=props; add.params_schema=schema; add.save(update_fields=["description","params_schema","updated_at"])
    update=Function.objects.filter(manifest_id="user_info.update_note").first()
    if update:
        schema=dict(update.params_schema); props=dict(schema.get("properties",{})); props["expires_at"]={"type":["string","null"],"description":"Optional ISO 8601 expiry; null makes it permanent; omit to leave unchanged."}; schema["properties"]=props; update.params_schema=schema; update.save(update_fields=["params_schema","updated_at"])

class Migration(migrations.Migration):
    dependencies=[("orchestration","0070_semantic_first_knowledge_guidance")]
    operations=[migrations.AddField(model_name="usernote",name="expires_at",field=models.DateTimeField(blank=True,db_index=True,null=True)),migrations.RunPython(configure,migrations.RunPython.noop)]
