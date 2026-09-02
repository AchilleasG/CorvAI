import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from chat.models import Chat, ChatMessage
from coding.delegations import FeatureDelegationService
from coding.files import attachment_context, materialize_inputs
from coding.models import CodingSession, CodingTurn, FeatureDelegation, ManagedFile
from coding.services import CodingSessionService
from ssh_connections.models import SshMachine


class ManagedFileApiTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.media.cleanup()

    def test_create_manage_download_and_delete_file(self):
        response = self.client.post("/api/files", data=json.dumps({
            "filename": "report.txt", "content": "hello", "tags": ["result", "result"],
            "metadata": {"kind": "artifact"},
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json(); file_id = payload["id"]
        self.assertEqual(payload["tags"], ["result"])
        self.assertEqual(payload["size"], 5)

        response = self.client.get(f"/api/files/{file_id}/content")
        self.assertEqual(b"".join(response.streaming_content), b"hello")

        response = self.client.patch(f"/api/files/{file_id}", data=json.dumps({
            "tags": ["final"], "metadata": {"reviewed": True}
        }), content_type="application/json")
        self.assertEqual(response.json()["metadata"], {"reviewed": True})
        self.assertEqual(self.client.get("/api/files", {"tag": "final"}).json()["files"][0]["id"], file_id)

        self.assertEqual(self.client.delete(f"/api/files/{file_id}").status_code, 200)
        self.assertFalse(ManagedFile.objects.filter(pk=file_id).exists())

    def test_uploaded_input_is_readable_by_chat_and_materialized_for_coding(self):
        machine = SshMachine.objects.create(
            name="Input host", host="input.example", username="developer",
            auth_type=SshMachine.AUTH_AGENT, allow_ai_commands=True,
        )
        session = CodingSession.objects.create(name="Input session", machine=machine)
        response = self.client.post("/api/files/upload", {
            "file": SimpleUploadedFile("requirements.md", b"Use a blue header", content_type="text/markdown"),
            "session_id": str(session.pk),
        })
        self.assertEqual(response.status_code, 200, response.content)
        file_id = response.json()["id"]
        self.assertIn("Use a blue header", attachment_context([file_id]))

        workspace = Path(self.media.name) / "coding-workspace"
        with patch.object(CodingSessionService, "workspace_dir", return_value=workspace):
            paths = materialize_inputs(session, [file_id])

        self.assertEqual(paths[0].read_text(encoding="utf-8"), "Use a blue header")
        self.assertEqual(paths[0].parent.name, "inputs")



    def test_delegation_uuid_upload_associates_artifact_with_selected_session(self):
        machine = SshMachine.objects.create(
            name="Artifact host",
            host="artifact.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        session = CodingSession.objects.create(name="Artifact session", machine=machine)
        delegation = FeatureDelegation.objects.create(
            session=session,
            title="Create a report",
            description="Return a PDF report.",
            acceptance_criteria=["PDF is downloadable"],
        )
        upload = SimpleUploadedFile("report.pdf", b"%PDF-test", content_type="application/pdf")

        response = self.client.post(
            f"/api/files/delegations/{delegation.pk}/upload",
            {"file": upload, "tags": '["final"]', "metadata": '{"kind":"artifact"}'},
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["delegation_id"], str(delegation.pk))
        self.assertEqual(payload["session_id"], str(session.pk))
        self.assertEqual(payload["filename"], "report.pdf")
        self.assertEqual(
            self.client.get("/api/files", {"session_id": session.pk}).json()["files"][0]["id"],
            payload["id"],
        )
        self.assertEqual(
            self.client.get("/api/files", {"delegation_id": delegation.pk}).json()["files"][0]["id"],
            payload["id"],
        )
        with override_settings(CORV_PUBLIC_BASE_URL="https://corv.example"):
            prompt = FeatureDelegationService._coder_prompt(delegation)
            delegation_payload = FeatureDelegationService.payload(delegation)
        self.assertIn(
            f"https://corv.example/api/files/delegations/{delegation.pk}/upload",
            prompt,
        )
        self.assertEqual(
            delegation_payload["artifact_upload_url"],
            f"https://corv.example/api/files/delegations/{delegation.pk}/upload",
        )

        protected_client = Client()
        with override_settings(APP_ACCESS_TOKEN="secret"):
            second = protected_client.post(
                f"/api/files/delegations/{delegation.pk}/upload",
                {"file": SimpleUploadedFile("public.txt", b"public artifact")},
            )
            self.assertEqual(second.status_code, 200, second.content)
            self.assertEqual(protected_client.get("/api/files").status_code, 401)

    def test_completed_turn_imports_workspace_artifacts_and_ignores_outside_paths(self):
        machine = SshMachine.objects.create(
            name="Turn artifact host",
            host="turn-artifact.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        session = CodingSession.objects.create(name="Turn artifact session", machine=machine)
        turn = CodingTurn.objects.create(
            session=session,
            prompt="Create a PDF",
            status=CodingTurn.STATUS_COMPLETED,
        )
        workspace = Path(self.media.name) / "workspace"
        workspace.mkdir()
        artifact = workspace / "returned report.pdf"
        artifact.write_bytes(b"%PDF-returned")
        outside = Path(self.media.name) / "private.txt"
        outside.write_text("do not import", encoding="utf-8")

        with patch.object(CodingSessionService, "workspace_dir", return_value=workspace):
            imported = CodingSessionService.capture_turn_artifacts(
                turn,
                f"[Download report]({artifact}) [outside]({outside})",
                ["returned report.pdf"],
            )

        self.assertEqual(len(imported), 1)
        item = imported[0]
        self.assertEqual(item.session, session)
        self.assertEqual(item.turn, turn)
        self.assertEqual(item.filename, "returned report.pdf")
        self.assertEqual(item.content_type, "application/pdf")
        self.assertEqual(item.tags, ["artifact"])
        self.assertEqual(ManagedFile.objects.filter(session=session).count(), 1)

    def test_attach_file_to_assistant_message(self):
        chat = Chat.objects.create()
        message = ChatMessage.objects.create(chat=chat, text="Result", role="assistant")
        created = self.client.post("/api/files", data=json.dumps({
            "filename": "result.json", "content": "{}", "content_type": "application/json"
        }), content_type="application/json").json()
        response = self.client.post(f"/api/files/{created['id']}/attach", data=json.dumps({
            "message_id": str(message.id)
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        message.refresh_from_db()
        self.assertEqual(message.metadata["attachments"][0]["id"], created["id"])
