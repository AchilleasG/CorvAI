from django.db import migrations


MODULE_DEFAULTS = {
    "name": "Files",
    "description": "Create, search, read, update, and delete persistent Corv files with metadata and tags.",
    "tags": ["files", "attachments", "coding"],
    "caller_instructions": (
        "Use file_handler.write_text when a user asks for a generated file or downloadable artifact. "
        "Files created during a chat job are automatically attached to the final assistant response. "
        "Use file IDs for subsequent reads or updates."
    ),
}

FUNCTIONS = {
    "file_handler.write_text": ("Create File", "Create a persistent Corv text file with metadata and tags.", ["file_name", "content"]),
    "file_handler.list_files": ("List Files", "List and search persistent Corv files.", []),
    "file_handler.read_file": ("Read File", "Read text from a persistent Corv file.", []),
    "file_handler.update_file": ("Update File", "Update file metadata, tags, filename, or content type.", ["file_id"]),
    "file_handler.delete_file": ("Delete File", "Delete a persistent Corv file.", ["file_id"]),
}


def forwards(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    module, _ = ToolModule.objects.update_or_create(slug="file_handler", defaults=MODULE_DEFAULTS)
    from orchestration.registry import FunctionRegistry
    for manifest_id, (name, description, required) in FUNCTIONS.items():
        registered = FunctionRegistry.get(manifest_id)
        ToolFunction.objects.update_or_create(manifest_id=manifest_id, defaults={
            "module": module, "name": name, "description": description,
            "params_schema": registered.params_schema if registered else {"type": "object", "properties": {}, "required": required},
            "return_schema": registered.return_schema if registered else {"type": "object"},
            "handler_ref": f"orchestration.tools.file_handler.{manifest_id.rsplit('.', 1)[-1]}",
            "tags": ["files"], "deprecated": False,
        })


def backwards(apps, schema_editor):
    apps.get_model("orchestration", "ToolFunction").objects.filter(
        manifest_id__in=["file_handler.update_file", "file_handler.delete_file"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0047_feature_delegation_qa_retry_mode")]
    operations = [migrations.RunPython(forwards, backwards)]
