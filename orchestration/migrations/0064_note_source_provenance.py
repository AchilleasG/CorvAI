from django.db import migrations


def make_note_source_system_managed(apps, schema_editor):
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    function = ToolFunction.objects.filter(manifest_id="user_info.add_note").first()
    if function is None:
        return
    schema = dict(function.params_schema or {})
    properties = dict(schema.get("properties") or {})
    properties.pop("source", None)
    schema["properties"] = properties
    function.params_schema = schema
    function.save(update_fields=["params_schema", "updated_at"])


def restore_note_source_parameter(apps, schema_editor):
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    function = ToolFunction.objects.filter(manifest_id="user_info.add_note").first()
    if function is None:
        return
    schema = dict(function.params_schema or {})
    properties = dict(schema.get("properties") or {})
    properties["source"] = {"type": "string"}
    schema["properties"] = properties
    function.params_schema = schema
    function.save(update_fields=["params_schema", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0063_workout_delete_plans_exercises")]

    operations = [
        migrations.RunPython(make_note_source_system_managed, restore_note_source_parameter),
    ]
