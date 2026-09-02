from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings

from chat.models import Chat, ChatMessage
from chat.services import ChatService
from coding.models import ManagedFile
from orchestration.models import Job
from orchestration.schemas import FunctionCallPayload
from orchestration.services import FunctionRunnerService
from orchestration.tools.file_handler import list_files, read_file, update_file, write_text
from ssh_connections.models import SshMachine


class FunctionalFileHandlerTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory(); self.override = override_settings(MEDIA_ROOT=self.media.name); self.override.enable()

    def tearDown(self):
        self.override.disable(); self.media.cleanup()

    def test_handler_uses_managed_files(self):
        created = write_text("answer.txt", "forty two", metadata={"source": "test"}, tags=["answer"])
        self.assertTrue(ManagedFile.objects.filter(pk=created["managed_file_id"]).exists())
        self.assertEqual(read_file(file_id=created["managed_file_id"])["content"], "forty two")
        self.assertEqual(list_files(tag="answer")["count"], 1)
        self.assertEqual(update_file(created["managed_file_id"], tags=["final"])["tags"], ["final"])

    def test_created_file_attaches_to_final_assistant_message(self):
        chat = Chat.objects.create(); job = Job.objects.create(chat=chat)
        result = FunctionRunnerService.run_function_call(FunctionCallPayload(
            trace_id="trace", function_id="file_handler.write_text",
            params={"file_name": "result.txt", "content": "done"}, job_id=str(job.id)), job=job)
        self.assertEqual(result.status, "ok")
        message = ChatService.add_message_to_chat(chat.id, "Here is the result", role="assistant", job=job)
        self.assertEqual(message.metadata["attachments"][0]["filename"], "result.txt")
        self.assertEqual(message.attached_files.count(), 1)
        job.refresh_from_db(); self.assertNotIn("pending_file_ids", job.metadata)


    def test_write_text_rejects_binary_formats(self):
        with self.assertRaisesRegex(ValueError, "only creates UTF-8 text files"):
            write_text("fake.pdf", "This is not a PDF", content_type="application/pdf")
        self.assertFalse(ManagedFile.objects.filter(filename="fake.pdf").exists())

    def test_fetched_ssh_binary_is_attached_to_chat_response(self):
        machine = SshMachine.objects.create(
            name="Default artifact machine",
            host="artifact.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
            is_default=True,
        )
        chat = Chat.objects.create()
        job = Job.objects.create(chat=chat)

        def download(_machine, remote_path, destination, max_bytes):
            self.assertEqual(_machine, machine)
            self.assertEqual(remote_path, "/tmp/report.pdf")
            Path(destination).write_bytes(b"%PDF-1.4\nreal pdf bytes\n%%EOF")
            return {"remote_path": remote_path, "size": Path(destination).stat().st_size}

        with patch(
            "orchestration.tools.ssh_connections.SshConnectionManager.download_file",
            side_effect=download,
        ):
            result = FunctionRunnerService.run_function_call(
                FunctionCallPayload(
                    trace_id="trace",
                    function_id="ssh_connections.fetch_file",
                    params={"remote_path": "/tmp/report.pdf", "filename": "report.pdf"},
                    job_id=str(job.id),
                ),
                job=job,
            )

        self.assertEqual(result.status, "ok", result.error_summary)
        item = ManagedFile.objects.get(filename="report.pdf")
        self.assertEqual(item.content_type, "application/pdf")
        self.assertEqual(item.metadata["machine_name"], machine.name)
        job.refresh_from_db()
        self.assertEqual(job.metadata["pending_file_ids"], [str(item.pk)])

        message = ChatService.add_message_to_chat(
            chat.id,
            "Here is the PDF.",
            role="assistant",
            job=job,
        )
        self.assertEqual(message.metadata["attachments"][0]["id"], str(item.pk))
        self.assertEqual(message.metadata["attachments"][0]["filename"], "report.pdf")
        self.assertEqual(message.attached_files.get(), item)
