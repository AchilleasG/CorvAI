import importlib
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from coding.models import CodingSession, FeatureDelegation
from coding.auth import CodexDeviceAuthService
from coding.delegations import FeatureDelegationService
from coding.services import CodingSessionService
from orchestration.models import PushToken, ToolModule
from orchestration.notifications import send_coding_push_to_all
from ssh_connections.models import SshMachine


class CodingToolLookupTests(TestCase):
    def setUp(self):
        self.machine = SshMachine.objects.create(
            name="StarSleep Server",
            host="starsleep.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        self.session = CodingSession.objects.create(
            name="StarSleep Main App",
            machine=self.machine,
            remote_working_directory="/srv/starsleep",
        )
        self.delegation = FeatureDelegation.objects.create(
            session=self.session,
            title="Bilingual bed descriptions",
            description="Add bilingual descriptions.",
            acceptance_criteria=["Both languages render"],
        )

    def test_coding_tools_resolve_display_names_without_uuid_validation_error(self):
        from orchestration.tools.coding_sessions import _delegation, _machine, _session

        self.assertEqual(_session("StarSleep Main App"), self.session)
        self.assertEqual(_machine("StarSleep Server"), self.machine)
        self.assertEqual(_delegation("Bilingual bed descriptions"), self.delegation)

    def test_coding_tools_still_resolve_uuids(self):
        from orchestration.tools.coding_sessions import _delegation, _machine, _session

        self.assertEqual(_session(str(self.session.pk)), self.session)
        self.assertEqual(_machine(str(self.machine.pk)), self.machine)
        self.assertEqual(_delegation(str(self.delegation.pk)), self.delegation)

    def test_ssh_tools_resolve_machine_display_name(self):
        from orchestration.tools.ssh_connections import _machine

        self.assertEqual(_machine("StarSleep Server"), self.machine)

    @patch("orchestration.notifications.send_fcm")
    @patch("orchestration.notifications.send_push")
    def test_coding_notifications_fan_out_to_expo_and_firebase(self, send_push, send_fcm):
        PushToken.objects.create(token="ExponentPushToken[test]", platform="ios")
        PushToken.objects.create(token="firebase-device-token", platform="android_fcm")

        send_coding_push_to_all(
            title="Feature · Test",
            body="QA passed",
            session_id=str(self.session.pk),
            delegation_id=str(self.delegation.pk),
            event="completed",
        )

        send_push.assert_called_once()
        send_fcm.assert_called_once()
        fcm_kwargs = send_fcm.call_args.kwargs
        self.assertEqual(fcm_kwargs["channel_id"], "corv_coding")
        self.assertEqual(fcm_kwargs["data"]["type"], "coding_session")
        self.assertEqual(fcm_kwargs["data"]["event"], "completed")


class CodingWorkspaceTests(SimpleTestCase):
    def test_device_login_output_exposes_only_official_link_and_code(self):
        url, code, minutes = CodexDeviceAuthService.parse_device_output(
            "Open https://auth.openai.com/codex/device\n"
            "Enter ABCD-EFGHJ (expires in 15 minutes)\n"
        )
        self.assertEqual(url, "https://auth.openai.com/codex/device")
        self.assertEqual(code, "ABCD-EFGHJ")
        self.assertEqual(minutes, 15)

    def test_device_login_rejects_non_openai_link(self):
        url, code, _minutes = CodexDeviceAuthService.parse_device_output(
            "Open https://example.invalid/steal and enter WXYZ-12345"
        )
        self.assertEqual(url, "")
        self.assertEqual(code, "WXYZ-12345")

    def test_tool_module_migration_uses_real_model_fields(self):
        migration = importlib.import_module("orchestration.migrations.0044_coding_sessions_module")
        field_names = {field.name for field in ToolModule._meta.get_fields()}
        self.assertTrue(set(migration.MODULE_DEFAULTS).issubset(field_names))

    def test_password_is_not_written_to_codex_instructions(self):
        machine = SshMachine(
            id=uuid.uuid4(),
            name="remote-dev",
            host="dev.example",
            username="developer",
            auth_type=SshMachine.AUTH_PASSWORD,
            allow_ai_commands=True,
        )
        machine.get_credentials = lambda: {"password": "top-secret-password"}
        session = CodingSession(
            id=uuid.uuid4(),
            name="work",
            machine=machine,
            remote_working_directory="/srv/project",
        )

        with tempfile.TemporaryDirectory() as root:
            with self.settings(CORV_CODING_DIR=root):
                with patch.object(CodingSessionService, "_host_key_line", return_value="dev.example ssh-ed25519 AAAA\n"):
                    workspace, environment = CodingSessionService.prepare_workspace(session)

            written_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(workspace).iterdir()
                if path.is_file()
            )

        self.assertNotIn("top-secret-password", written_text)
        self.assertEqual(environment["SSHPASS"], "top-secret-password")
        self.assertIn("sshpass -e", written_text)
        command = CodingSessionService.managed_codex_command("codex", Path("/tmp/work"))
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertNotIn("--ephemeral", command)

    def test_interactive_resume_keeps_full_access_and_saved_thread(self):
        command = CodingSessionService.interactive_codex_command(
            "codex", Path("/tmp/work"), "0199-session-id"
        )
        self.assertEqual(command[:3], ["codex", "resume", "--include-non-interactive"])
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("0199-session-id", command)

    def test_disabled_machine_cannot_prepare_codex_access(self):
        machine = SshMachine(
            id=uuid.uuid4(),
            name="locked",
            host="locked.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=False,
        )
        session = CodingSession(id=uuid.uuid4(), name="locked", machine=machine)
        with self.assertRaises(PermissionError):
            CodingSessionService.prepare_workspace(session)

    def test_qa_codex_uses_independent_resumable_full_access_thread(self):
        fresh = FeatureDelegationService._qa_command(
            "codex", Path("/tmp/work"), "", ["/tmp/evidence.png"]
        )
        resumed = FeatureDelegationService._qa_command(
            "codex", Path("/tmp/work"), "qa-thread-id", ["/tmp/evidence.png"]
        )
        self.assertEqual(fresh[:2], ["codex", "exec"])
        self.assertEqual(resumed[:3], ["codex", "exec", "resume"])
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", fresh)
        self.assertIn("--output-schema", fresh)
        self.assertIn("--image", resumed)
        self.assertIn("qa-thread-id", resumed)

    def test_qa_prompt_requires_independent_testing_without_code_edits(self):
        prompt_source = FeatureDelegationService._qa_prompt.__func__.__code__.co_consts
        rendered_source = " ".join(str(item) for item in prompt_source)
        self.assertIn("independent QA bot", rendered_source)
        self.assertIn("Do not edit application code", rendered_source)
        self.assertIn("browser harness", rendered_source)
