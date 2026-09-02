from django.db import migrations


FILE_GUIDANCE = (
    " file_handler.write_text is only for genuine UTF-8 text artifacts such as TXT, Markdown, CSV, "
    "JSON, XML, YAML, and source code. Never use it to simulate a PDF, image, Office document, "
    "archive, audio, video, or any other binary format by putting textual content under a binary "
    "extension or MIME type. For binary artifacts, create the real file with coding or SSH tools."
)

SSH_GUIDANCE = (
    " When SSH commands create a file the user needs, the remote path is not accessible to the user. "
    "Call ssh_connections.fetch_file with the absolute remote path before the final response. Its "
    "managed_file_id causes Corv to attach the file to the chat automatically. Do not claim a remote "
    "file is attached or downloadable until fetch_file succeeds."
)


def configure_remote_file_fetch(apps, schema_editor):
    ToolModule = apps.get_model("orchestration", "ToolModule")
    ToolFunction = apps.get_model("orchestration", "ToolFunction")
    from orchestration.registry import FunctionRegistry

    files = ToolModule.objects.get(slug="file_handler")
    if FILE_GUIDANCE.strip() not in files.caller_instructions:
        files.caller_instructions = files.caller_instructions.rstrip() + FILE_GUIDANCE
        files.save(update_fields=["caller_instructions", "updated_at"])

    ssh = ToolModule.objects.get(slug="ssh_connections")
    if SSH_GUIDANCE.strip() not in ssh.caller_instructions:
        ssh.caller_instructions = ssh.caller_instructions.rstrip() + SSH_GUIDANCE
        ssh.save(update_fields=["caller_instructions", "updated_at"])

    writer = ToolFunction.objects.get(manifest_id="file_handler.write_text")
    writer.description = (
        "Create a UTF-8 text file such as TXT, Markdown, CSV, JSON, XML, YAML, or source code. "
        "Never use for PDFs or other binary formats."
    )
    writer.save(update_fields=["description", "updated_at"])

    registered = FunctionRegistry.get("ssh_connections.fetch_file")
    ToolFunction.objects.update_or_create(
        manifest_id="ssh_connections.fetch_file",
        defaults={
            "module": ssh,
            "name": "Fetch Remote File",
            "description": registered.description,
            "params_schema": registered.params_schema,
            "return_schema": registered.return_schema,
            "handler_ref": registered.handler_ref,
            "tags": ["ssh", "files", "attachments"],
            "examples": [
                {
                    "user_prompt": "Make a PDF on my default machine and send it to me",
                    "params": {"remote_path": "/tmp/report.pdf", "filename": "report.pdf"},
                },
                {
                    "user_prompt": "Attach the spreadsheet generated on Animus",
                    "params": {
                        "machine": "Animus Server",
                        "remote_path": "/tmp/results.xlsx",
                        "filename": "results.xlsx",
                    },
                },
            ],
            "deprecated": False,
        },
    )


def reverse_remote_file_fetch(apps, schema_editor):
    apps.get_model("orchestration", "ToolFunction").objects.filter(
        manifest_id="ssh_connections.fetch_file"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("orchestration", "0051_default_ssh_machine_guidance")]
    operations = [migrations.RunPython(configure_remote_file_fetch, reverse_remote_file_fetch)]
