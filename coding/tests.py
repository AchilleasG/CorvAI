import importlib
import io
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from coding.models import CodingDelegationWatch, CodingSession, CodingTurn, FeatureDelegation, FeatureQaRun
from coding.auth import CodexAuthService, CodexDeviceAuthService
from coding.browser_runner import InteractiveBrowserSession, _start_tunnel
from coding.delegations import FeatureDelegationService
from coding.services import CodingSessionService
from coding.ssh_broker import CodingSshBroker
from coding.ssh_bridge import run_command as run_brokered_command
from chat.models import ChatMessage
from coding.chat_waits import CodingChatWaitService
from orchestration.models import CallSession, CallTranscriptEntry, Job, PushToken, ToolModule
from orchestration.schemas import FunctionCallPayload
from orchestration.services import FunctionRunnerService
from orchestration.notifications import send_coding_push_to_all
from ssh_connections.models import SshCommandRecord, SshMachine


TEST_MODULE_SECRET = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


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

    def test_get_activity_returns_running_delegations_and_recent_logs(self):
        from orchestration.tools.coding_sessions import get_activity

        self.session.status = CodingSession.STATUS_RUNNING
        self.session.save(update_fields=["status", "updated_at"])
        self.delegation.status = FeatureDelegation.STATUS_QA
        self.delegation.save(update_fields=["status", "updated_at"])
        FeatureQaRun.objects.create(
            delegation=self.delegation,
            iteration=1,
            status=FeatureQaRun.STATUS_RUNNING,
        )
        CodingTurn.objects.create(
            session=self.session,
            prompt="Implement the feature",
            status=CodingTurn.STATUS_RUNNING,
            event_log="Building the web application now",
        )

        payload = get_activity(recent_log_chars=1000)

        self.assertTrue(payload["has_running_work"])
        self.assertEqual(payload["active_session_count"], 1)
        self.assertEqual(payload["active_delegation_count"], 1)
        self.assertIn("Building the web application now", payload["sessions"][0]["recent_logs"])
        self.assertEqual(payload["delegations"][0]["status"], FeatureDelegation.STATUS_QA)

    def test_get_activity_excludes_completed_work_by_default(self):
        from orchestration.tools.coding_sessions import get_activity

        self.delegation.status = FeatureDelegation.STATUS_COMPLETED
        self.delegation.save(update_fields=["status", "updated_at"])

        payload = get_activity()

        self.assertFalse(payload["has_running_work"])
        self.assertEqual(payload["delegations"], [])

    def test_action_modules_explain_codex_vs_direct_ssh_routing(self):
        from orchestration.models import ToolFunction

        coding_module = ToolModule.objects.get(slug="coding_sessions")
        ssh_module = ToolModule.objects.get(slug="ssh_connections")
        delegate = ToolFunction.objects.get(manifest_id="coding_sessions.delegate_task")
        command = ToolFunction.objects.get(manifest_id="ssh_connections.run_command")

        self.assertIn("existing coding session", coding_module.caller_instructions)
        self.assertIn("ssh_connections.run_command", coding_module.caller_instructions)
        self.assertIn("coding_sessions.delegate_task", ssh_module.caller_instructions)
        self.assertIn("saved thread", delegate.description)
        self.assertTrue(delegate.examples)
        self.assertIn("exact command and path", command.description)
        self.assertIn("Do not use this for finding", command.description)
        self.assertIn("find, locate, search for, or discover", coding_module.caller_instructions)
        self.assertTrue(command.examples)

    def test_coding_tools_still_resolve_uuids(self):
        from orchestration.tools.coding_sessions import _delegation, _machine, _session

        self.assertEqual(_session(str(self.session.pk)), self.session)
        self.assertEqual(_machine(str(self.machine.pk)), self.machine)
        self.assertEqual(_delegation(str(self.delegation.pk)), self.delegation)

    def test_ssh_tools_resolve_machine_display_name(self):
        from orchestration.tools.ssh_connections import _machine

        self.assertEqual(_machine("StarSleep Server"), self.machine)

    def test_stopped_session_can_resume_with_saved_codex_thread(self):
        self.session.status = CodingSession.STATUS_STOPPED
        self.session.codex_thread_id = "saved-codex-thread"
        self.session.stopped_at = timezone.now()
        self.session.save(update_fields=["status", "codex_thread_id", "stopped_at"])

        payload = CodingSessionService.resume(self.session)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, CodingSession.STATUS_READY)
        self.assertIsNone(self.session.stopped_at)
        self.assertEqual(self.session.codex_thread_id, "saved-codex-thread")
        self.assertEqual(payload["status"], CodingSession.STATUS_READY)

    def test_simple_task_choices_are_recovered_from_waiting_turn(self):
        self.session.status = CodingSession.STATUS_NEEDS_INPUT
        self.session.pending_question = ""
        self.session.pending_options = []
        self.session.save(update_fields=["status", "pending_question", "pending_options"])
        CodingTurn.objects.create(
            session=self.session,
            prompt="Make the small change",
            status=CodingTurn.STATUS_NEEDS_INPUT,
            question="Which implementation should I use?",
            options=["Use the existing component", "Create a new component"],
        )

        payload = CodingSessionService.session_payload(self.session)

        self.assertEqual(payload["pending_question"], "Which implementation should I use?")
        self.assertEqual(
            payload["pending_options"],
            ["Use the existing component", "Create a new component"],
        )

    def test_simple_task_without_question_gets_visible_fallback_prompt(self):
        self.session.status = CodingSession.STATUS_NEEDS_INPUT
        self.session.pending_question = ""
        self.session.pending_options = ["Continue", "Stop"]
        self.session.save(update_fields=["status", "pending_question", "pending_options"])

        payload = CodingSessionService.session_payload(self.session)

        self.assertEqual(payload["pending_question"], "Choose how Codex should continue.")
        self.assertEqual(payload["pending_options"], ["Continue", "Stop"])

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


class DelegationRestartTests(TestCase):
    def setUp(self):
        self.machine = SshMachine.objects.create(
            name="Restart target",
            host="restart.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        self.session = CodingSession.objects.create(
            name="Restart session",
            machine=self.machine,
            status=CodingSession.STATUS_RUNNING,
        )

    def test_task_delegation_automatically_continues_after_restart(self):
        interrupted = CodingTurn.objects.create(
            session=self.session,
            prompt="Finish the task",
            source=CodingTurn.SOURCE_UI,
            status=CodingTurn.STATUS_RUNNING,
        )

        with (
            patch.object(CodingSessionService, "tmux_alive", return_value=False),
            patch.object(CodingSessionService, "start_turn") as start_turn,
        ):
            resumed = CodingSessionService.recover_interrupted_turns()

        interrupted.refresh_from_db()
        self.assertEqual(interrupted.status, CodingTurn.STATUS_CANCELLED)
        self.assertIn("process restart", interrupted.error)
        start_turn.assert_called_once_with(
            self.session,
            "Finish the task",
            source=CodingTurn.SOURCE_UI,
        )
        self.assertEqual(resumed, 1)

    def test_session_read_does_not_trigger_restart_recovery(self):
        interrupted = CodingTurn.objects.create(
            session=self.session, prompt="Do not duplicate me",
            source=CodingTurn.SOURCE_UI, status=CodingTurn.STATUS_RUNNING,
        )
        with patch.object(CodingSessionService, "start_turn") as start_turn:
            CodingSessionService.session_payload(self.session)
        interrupted.refresh_from_db()
        self.assertEqual(interrupted.status, CodingTurn.STATUS_RUNNING)
        start_turn.assert_not_called()

    def test_manual_stop_is_not_automatically_resumed(self):
        self.session.status = CodingSession.STATUS_STOPPED
        self.session.save(update_fields=["status", "updated_at"])
        CodingTurn.objects.create(
            session=self.session, prompt="Stay stopped",
            source=CodingTurn.SOURCE_UI, status=CodingTurn.STATUS_CANCELLED,
        )
        with patch.object(CodingSessionService, "start_turn") as start_turn:
            resumed = CodingSessionService.recover_interrupted_turns()
        self.assertEqual(resumed, 0)
        start_turn.assert_not_called()

    def test_restart_recovery_claims_a_turn_only_once(self):
        CodingTurn.objects.create(session=self.session, prompt="Resume once", status=CodingTurn.STATUS_RUNNING)
        with patch.object(CodingSessionService, "start_turn") as start_turn:
            self.assertEqual(CodingSessionService.recover_interrupted_turns(), 1)
            self.assertEqual(CodingSessionService.recover_interrupted_turns(), 0)
        start_turn.assert_called_once()

    def test_feature_coding_retries_same_iteration_after_restart(self):
        delegation = FeatureDelegation.objects.create(
            session=self.session,
            title="Restartable feature",
            description="Keep working after Corv restarts.",
            acceptance_criteria=["Work continues"],
            status=FeatureDelegation.STATUS_FIXING,
            current_iteration=3,
        )
        interrupted = CodingTurn.objects.create(
            session=self.session,
            prompt="Fix the feature",
            source=CodingTurn.SOURCE_FEATURE,
            status=CodingTurn.STATUS_RUNNING,
        )
        delegation.coding_turn_ids = [str(interrupted.pk)]
        delegation.save(update_fields=["coding_turn_ids"])

        with patch.object(FeatureDelegationService, "_spawn") as spawn:
            FeatureDelegationService.reconcile(delegation)

        delegation.refresh_from_db()
        interrupted.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(interrupted.status, CodingTurn.STATUS_CANCELLED)
        self.assertEqual(delegation.status, FeatureDelegation.STATUS_QUEUED)
        self.assertEqual(delegation.current_iteration, 2)
        self.assertEqual(self.session.status, CodingSession.STATUS_RUNNING)
        self.assertEqual(delegation.pending_question, "")
        spawn.assert_called_once_with(delegation, qa_only=False)

    def test_feature_qa_automatically_retries_qa_after_restart(self):
        delegation = FeatureDelegation.objects.create(
            session=self.session,
            title="Restartable QA",
            description="Keep testing after Corv restarts.",
            acceptance_criteria=["QA continues"],
            status=FeatureDelegation.STATUS_QA,
            current_iteration=2,
        )
        qa_run = FeatureQaRun.objects.create(
            delegation=delegation,
            iteration=2,
            status=FeatureQaRun.STATUS_RUNNING,
        )

        with patch.object(FeatureDelegationService, "_spawn") as spawn:
            FeatureDelegationService.reconcile(delegation)

        delegation.refresh_from_db()
        qa_run.refresh_from_db()
        self.assertEqual(qa_run.status, FeatureQaRun.STATUS_ERROR)
        self.assertIn("process restart", qa_run.error)
        self.assertEqual(delegation.status, FeatureDelegation.STATUS_QA)
        self.assertEqual(delegation.current_iteration, 2)
        spawn.assert_called_once_with(delegation, qa_only=True)


class CodexAuthSettingsTests(SimpleTestCase):
    def setUp(self):
        self.setting_values = {}
        self.get_setting = patch.object(
            CodexAuthService,
            "_setting",
            side_effect=lambda key, default="": self.setting_values.get(key, default),
        )
        self.set_setting = patch.object(
            CodexAuthService,
            "_set_setting",
            side_effect=lambda key, value: self.setting_values.__setitem__(key, value),
        )
        self.get_setting.start()
        self.set_setting.start()
        self.addCleanup(self.get_setting.stop)
        self.addCleanup(self.set_setting.stop)

    def test_api_key_is_encrypted_and_response_only_contains_a_hint(self):
        from Corv.config import settings as corv_settings

        with (
            patch.object(corv_settings, "module_secret_key", TEST_MODULE_SECRET),
            patch.object(CodexAuthService, "_write_api_login") as write_login,
        ):
            payload = CodexAuthService.update("api_key", "sk-project-super-secret")
            encrypted = self.setting_values[CodexAuthService.API_KEY_SETTING]

        self.assertNotIn("sk-project-super-secret", encrypted)
        self.assertNotIn("api_key", payload)
        self.assertTrue(payload["codex_api_key_configured"])
        self.assertEqual(payload["codex_api_key_hint"], "••••cret")
        self.assertEqual(payload["codex_auth_mode"], "api_key")
        write_login.assert_called_once_with("sk-project-super-secret")

    def test_switching_back_to_profile_keeps_saved_api_key(self):
        from Corv.config import settings as corv_settings

        with (
            patch.object(corv_settings, "module_secret_key", TEST_MODULE_SECRET),
            patch.object(CodexAuthService, "_write_api_login"),
        ):
            CodexAuthService.update("api_key", "sk-kept-between-modes")
            payload = CodexAuthService.update("profile")
            saved_key = CodexAuthService.api_key()

        self.assertEqual(payload["codex_auth_mode"], "profile")
        self.assertEqual(saved_key, "sk-kept-between-modes")

    @patch.object(CodexAuthService, "profile_status", return_value=(True, "Logged in using ChatGPT"))
    @patch.object(CodexAuthService, "_app_server_rate_limits")
    @patch.object(CodexAuthService, "mode", return_value=CodexAuthService.MODE_PROFILE)
    def test_profile_usage_normalizes_available_windows(self, _mode, app_server, _status):
        CodexAuthService._usage_cache = None
        app_server.return_value = {"id": 2, "result": {"rateLimits": {"planType": "plus", "primary": {"usedPercent": 23, "resetsAt": 2000000000, "windowDurationMins": 300}, "secondary": {"usedPercent": 51, "resetsAt": 2000001000, "windowDurationMins": 10080}, "credits": {"hasCredits": True, "unlimited": False, "balance": "12.50"}}}}

        payload = CodexAuthService.profile_usage("/usr/bin/codex", refresh=True)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["plan_type"], "plus")
        self.assertEqual(payload["primary"]["remaining_percent"], 77)
        self.assertEqual(payload["secondary"]["remaining_percent"], 49)
        self.assertEqual(payload["credits"]["balance"], "12.50")

    @patch.object(CodexAuthService, "profile_status", return_value=(True, "Logged in using an API key"))
    @patch.object(CodexAuthService, "_app_server_rate_limits")
    @patch.object(CodexAuthService, "mode", return_value=CodexAuthService.MODE_PROFILE)
    def test_profile_usage_explains_api_key_backed_profile(self, _mode, app_server, _status):
        CodexAuthService._usage_cache = None
        app_server.return_value = {"id": 2, "error": {"message": "chatgpt authentication required to read rate limits"}}

        payload = CodexAuthService.profile_usage("/usr/bin/codex", refresh=True)

        self.assertFalse(payload["available"])
        self.assertIn("using an API key", payload["reason"])

    def test_profile_mode_removes_inherited_api_key(self):
        environment = CodexAuthService.profile_environment(
            {"OPENAI_API_KEY": "should-not-leak", "CODEX_HOME": "/profile-home"}
        )

        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertEqual(environment["CODEX_HOME"], "/profile-home")

    def test_api_login_uses_isolated_codex_home_and_stdin(self):
        completed = MagicMock(returncode=0, stdout="Successfully logged in", stderr="")
        with tempfile.TemporaryDirectory() as root:
            with (
                self.settings(CORV_CODING_DIR=root),
                patch("coding.auth.subprocess.run", return_value=completed) as run,
            ):
                CodexAuthService._write_api_login("sk-private")

        self.assertEqual(run.call_args.args[0][-2:], ["login", "--with-api-key"])
        self.assertEqual(run.call_args.kwargs["input"], "sk-private")
        self.assertNotIn("OPENAI_API_KEY", run.call_args.kwargs["env"])
        self.assertTrue(run.call_args.kwargs["env"]["CODEX_HOME"].endswith(".codex-api-key"))


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
            workspace_path = Path(root) / str(session.pk)
            workspace_path.mkdir()
            (workspace_path / "identity").write_text("legacy-private-key", encoding="utf-8")
            (workspace_path / "ssh_config").write_text("legacy-config", encoding="utf-8")
            with self.settings(CORV_CODING_DIR=root):
                with (
                    patch("coding.services.SshConnectionManager.connect") as connect,
                    patch.object(CodingSshBroker, "ensure") as ensure_broker,
                    patch.dict("coding.services.os.environ", {"SSHPASS": "inherited-secret"}),
                ):
                    workspace, environment = CodingSessionService.prepare_workspace(session)

            written_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(workspace).iterdir()
                if path.is_file()
            )
            identity_exists = (Path(workspace) / "identity").exists()
            ssh_config_exists = (Path(workspace) / "ssh_config").exists()

        self.assertNotIn("top-secret-password", written_text)
        self.assertNotIn("SSHPASS", environment)
        self.assertNotIn("sshpass", written_text)
        self.assertIn("ssh_bridge.py", written_text)
        self.assertIn("--socket", written_text)
        self.assertIn(" command -- \"$@\"", written_text)
        self.assertFalse(identity_exists)
        self.assertFalse(ssh_config_exists)
        connect.assert_called_once_with(machine)
        ensure_broker.assert_called_once()
        command = CodingSessionService.managed_codex_command("codex", Path("/tmp/work"))
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertNotIn("--ephemeral", command)

    def test_workspace_ssh_wrapper_sends_commands_to_corv_broker(self):
        output = io.StringIO()
        error = io.StringIO()
        with (
            patch(
                "coding.ssh_bridge._request",
                return_value={
                    "ok": True,
                    "stdout": "remote output\n",
                    "stderr": "",
                    "exit_status": 7,
                    "truncated": False,
                },
            ) as request,
            patch("sys.stdout", output),
            patch("sys.stderr", error),
        ):
            status = run_brokered_command("/tmp/corv.sock", ["cd /srv/app &&", "pytest -q"])

        self.assertEqual(status, 7)
        self.assertEqual(output.getvalue(), "remote output\n")
        self.assertEqual(error.getvalue(), "")
        request.assert_called_once_with(
            "/tmp/corv.sock",
            {"operation": "command", "command": "cd /srv/app && pytest -q"},
        )

    def test_broker_routes_assistant_command_through_isolated_persistent_transport_channel(self):
        machine = SshMachine(
            id=uuid.uuid4(),
            name="managed-target",
            host="target.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        session = CodingSession(id=uuid.uuid4(), name="work", machine=machine)
        broker = CodingSshBroker(session, Path("/tmp/corv-test.sock"))
        handler = MagicMock()
        handler.wfile = io.BytesIO()
        with patch(
            "coding.ssh_broker.SshConnectionManager.run_exec_command",
            return_value={
                "stdout": "ok\n",
                "stderr": "",
                "exit_status": 0,
                "truncated": False,
            },
        ) as run_exec:
            broker._handle_command(handler, {"command": "git status --short"})

        self.assertEqual(run_exec.call_args.args, (machine, "git status --short"))
        self.assertEqual(
            run_exec.call_args.kwargs["source"],
            SshCommandRecord.SOURCE_ASSISTANT,
        )
        self.assertTrue(json.loads(handler.wfile.getvalue())["ok"])

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
        self.assertIn("persistent interactive Chrome browser", rendered_source)
        self.assertIn("exactly one browser action", rendered_source)

    def test_interactive_browser_keeps_driver_alive_between_observations(self):
        class FakeElement:
            text = "Welcome to the test app"

        class FakeDriver:
            def __init__(self, **_kwargs):
                self.current_url = "about:blank"
                self.title = "Test app"
                self.quit_called = False

            def set_page_load_timeout(self, _timeout):
                pass

            def get(self, url):
                self.current_url = url

            def save_screenshot(self, path):
                Path(path).write_bytes(b"png")
                return True

            def find_element(self, *_args):
                return FakeElement()

            def execute_script(self, *_args):
                return [{"selector": "#continue", "tag": "button", "text": "Continue"}]

            def get_log(self, _kind):
                return []

            def quit(self):
                self.quit_called = True

        created = []

        def driver_factory(**kwargs):
            driver = FakeDriver(**kwargs)
            created.append(driver)
            return driver

        with tempfile.TemporaryDirectory() as root:
            session = InteractiveBrowserSession(Path(root), driver_factory=driver_factory)
            first = session.perform({"type": "start", "url": "http://127.0.0.1:3000"})
            driver = session.driver
            second = session.perform({"type": "goto", "url": "http://127.0.0.1:3000/settings"})
            session.close()

        self.assertTrue(first["success"])
        self.assertEqual(first["step"], 1)
        self.assertEqual(second["step"], 2)
        self.assertEqual(len(created), 1)
        self.assertIs(created[0], driver)
        self.assertEqual(second["url"], "http://127.0.0.1:3000/settings")
        self.assertTrue(driver.quit_called)

    def test_tunnel_wrapper_is_resolved_from_explicit_session_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / "session-workspace"
            workspace.mkdir()
            wrapper = workspace / "ssh-tunnel"
            wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
            wrapper.chmod(0o700)
            process = MagicMock()
            process.poll.return_value = None
            connection = MagicMock()
            connection.__enter__.return_value = connection
            with (
                patch("coding.browser_runner.subprocess.Popen", return_value=process) as popen,
                patch("coding.browser_runner.socket.create_connection", return_value=connection),
            ):
                result = _start_tunnel(
                    {"ssh_tunnel": {"local_port": 18443, "remote_port": 3000}},
                    1,
                    workspace_dir=workspace,
                )

        self.assertIs(result, process)
        self.assertEqual(popen.call_args.args[0][0], str(wrapper.resolve()))
        self.assertEqual(popen.call_args.kwargs["cwd"], workspace.resolve())

    def test_qa_followup_includes_browser_observation(self):
        prompt = FeatureDelegationService._browser_followup_prompt(
            {
                "success": True,
                "url": "http://127.0.0.1:3000/dashboard",
                "title": "Dashboard",
                "visible_text": "Signed in",
                "interactive_elements": [{"selector": "#save", "text": "Save"}],
                "console": [],
            },
            2,
            60,
        )
        self.assertIn("current screenshot is attached", prompt)
        self.assertIn("#save", prompt)
        self.assertIn("step 2 of at most 60", prompt)


class FeatureQaFlowTests(TestCase):
    def setUp(self):
        self.machine = SshMachine.objects.create(
            name="QA target",
            host="qa.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        self.session = CodingSession.objects.create(
            name="QA session",
            machine=self.machine,
            remote_working_directory="/srv/app",
        )
        self.delegation = FeatureDelegation.objects.create(
            session=self.session,
            title="Search flow",
            description="Exercise search through the browser.",
            acceptance_criteria=["Search results work"],
            status=FeatureDelegation.STATUS_QA,
            current_iteration=2,
        )

    def test_meaningful_browser_interaction_can_support_passing_verdict(self):
        results = [
            ({"status": "action", "action": {"type": "start"}}, "thread", []),
            ({"status": "action", "action": {"type": "click"}}, "thread", []),
            ({
                "status": "passed",
                "summary": "Search flow passed",
                "failures": [],
                "evidence": [],
                "question": "",
                "options": [],
                "browser_applicable": True,
                "action": {"type": "none"},
            }, "thread", []),
        ]
        browser = MagicMock()
        browser.perform.side_effect = [
            {"success": True, "step": 1, "url": "https://app.example", "screenshot": "/tmp/start.png"},
            {"success": True, "step": 2, "url": "https://app.example?q=test", "screenshot": "/tmp/result.png"},
        ]
        with tempfile.TemporaryDirectory() as root:
            with self.settings(CORV_CODING_DIR=root):
                with (
                    patch.object(FeatureDelegationService, "_execute_qa_turn", side_effect=results),
                    patch("coding.delegations.InteractiveBrowserSession", return_value=browser) as browser_class,
                ):
                    qa_run = FeatureDelegationService._run_qa(self.delegation)
                expected_workspace = CodingSessionService.workspace_dir(self.session)

        self.assertEqual(qa_run.status, FeatureQaRun.STATUS_PASSED, qa_run.error)
        self.assertEqual(qa_run.summary, "Search flow passed")
        self.assertEqual(
            browser_class.call_args.kwargs["workspace_dir"],
            expected_workspace,
        )

    def test_blocked_qa_auto_resume_retries_qa_without_coding_iteration(self):
        self.delegation.status = FeatureDelegation.STATUS_NEEDS_INPUT
        self.delegation.current_iteration = 4
        self.delegation.pending_question = "Tunnel unavailable"
        self.delegation.save()
        FeatureQaRun.objects.create(
            delegation=self.delegation,
            iteration=4,
            status=FeatureQaRun.STATUS_BLOCKED,
            question="Tunnel unavailable",
            completed_at=timezone.now(),
        )
        self.assertTrue(FeatureDelegationService.payload(self.delegation)["can_retry_qa"])

        with patch.object(FeatureDelegationService, "_spawn") as spawn:
            FeatureDelegationService.resume(self.delegation, "Tunnel restored")

        self.delegation.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(self.delegation.status, FeatureDelegation.STATUS_QA)
        self.assertEqual(self.delegation.current_iteration, 4)
        self.assertEqual(self.session.status, CodingSession.STATUS_RUNNING)
        spawn.assert_called_once_with(
            self.delegation,
            continuation="Tunnel restored",
            qa_only=True,
        )

    def test_explicit_coding_resume_starts_a_new_coding_cycle(self):
        self.delegation.status = FeatureDelegation.STATUS_NEEDS_INPUT
        self.delegation.save(update_fields=["status"])
        FeatureQaRun.objects.create(
            delegation=self.delegation,
            iteration=2,
            status=FeatureQaRun.STATUS_BLOCKED,
            completed_at=timezone.now(),
        )

        with patch.object(FeatureDelegationService, "_spawn") as spawn:
            FeatureDelegationService.resume(self.delegation, "Change the app", mode="coding")

        self.delegation.refresh_from_db()
        self.assertEqual(self.delegation.status, FeatureDelegation.STATUS_QUEUED)
        spawn.assert_called_once_with(
            self.delegation,
            continuation="Change the app",
            qa_only=False,
        )

    def test_stopped_delegation_can_retry_its_blocked_qa(self):
        self.delegation.status = FeatureDelegation.STATUS_STOPPED
        self.delegation.stopped_at = timezone.now()
        self.delegation.save(update_fields=["status", "stopped_at"])
        FeatureQaRun.objects.create(
            delegation=self.delegation,
            iteration=2,
            status=FeatureQaRun.STATUS_BLOCKED,
            completed_at=timezone.now(),
        )
        self.assertTrue(FeatureDelegationService.payload(self.delegation)["can_retry_qa"])

        with patch.object(FeatureDelegationService, "_spawn") as spawn:
            FeatureDelegationService.resume(self.delegation, mode="qa")

        self.delegation.refresh_from_db()
        self.assertEqual(self.delegation.status, FeatureDelegation.STATUS_QA)
        self.assertIsNone(self.delegation.stopped_at)
        spawn.assert_called_once_with(self.delegation, continuation="", qa_only=True)


class CodingChatWaitTests(TestCase):
    def setUp(self):
        self.machine = SshMachine.objects.create(
            name="Wait machine",
            host="wait.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        self.session = CodingSession.objects.create(
            name="Wait session", machine=self.machine, remote_working_directory="/srv/app"
        )
        from chat.models import Chat
        self.chat = Chat.objects.create()

    def test_completed_turn_reports_back_once_to_originating_chat(self):
        turn = CodingTurn.objects.create(
            session=self.session,
            prompt="Inspect the repository",
            status=CodingTurn.STATUS_COMPLETED,
            summary="Found the requested project at /srv/app/ExamSense.",
        )
        watch = CodingChatWaitService.watch_turn(chat=self.chat, turn=turn)

        message = ChatMessage.objects.get(chat=self.chat, metadata__kind="coding_delegation_update")
        self.assertIn("Codex finished", message.text)
        self.assertIn("/srv/app/ExamSense", message.text)
        watch.refresh_from_db()
        self.assertFalse(watch.active)

        CodingChatWaitService.publish_for_session(self.session)
        self.assertEqual(ChatMessage.objects.filter(chat=self.chat, metadata__kind="coding_delegation_update").count(), 1)

    def test_question_and_options_are_reported_then_watch_follows_answer_turn(self):
        first = CodingTurn.objects.create(
            session=self.session,
            prompt="Make the change",
            status=CodingTurn.STATUS_NEEDS_INPUT,
            question="Which database should I use?",
            options=["Postgres", "SQLite"],
        )
        watch = CodingChatWaitService.watch_turn(chat=self.chat, turn=first)
        question = ChatMessage.objects.get(chat=self.chat, metadata__event="needs_input")
        self.assertIn("Which database", question.text)
        self.assertIn("Postgres", question.text)
        watch.refresh_from_db()
        self.assertTrue(watch.active)

        answer_turn = CodingTurn.objects.create(
            session=self.session,
            prompt="Decision from the user: Postgres",
            status=CodingTurn.STATUS_COMPLETED,
            summary="Implemented with Postgres.",
        )
        CodingChatWaitService.advance_turn(chat=self.chat, turn=answer_turn)
        CodingChatWaitService.publish_for_session(self.session)
        self.assertTrue(ChatMessage.objects.filter(chat=self.chat, metadata__event="completed").exists())
        watch.refresh_from_db()
        self.assertFalse(watch.active)

    @patch("orchestration.services.FunctionRegistry.resolve_callable")
    def test_runner_registers_requested_wait_against_job_chat(self, resolve):
        turn = CodingTurn.objects.create(
            session=self.session, prompt="Investigate", status=CodingTurn.STATUS_QUEUED
        )
        resolve.return_value = lambda **_params: {
            "delegated_turn_id": str(turn.pk),
            "wait_for_completion": True,
        }
        job = Job.objects.create(chat=self.chat, status=Job.STATUS_RUNNING)

        result = FunctionRunnerService.run_function_call(
            FunctionCallPayload(
                trace_id="wait-test",
                function_id="coding_sessions.delegate_task",
                params={"session": str(self.session.pk), "task": "Investigate", "wait_for_completion": True},
            ),
            job=job,
        )

        self.assertEqual(result.status, "ok")
        self.assertTrue(CodingDelegationWatch.objects.filter(chat=self.chat, turn=turn, active=True).exists())

    def test_feature_question_is_delivered_to_chat(self):
        delegation = FeatureDelegation.objects.create(
            session=self.session,
            title="Database choice",
            description="Implement persistence",
            acceptance_criteria=["Data persists"],
            status=FeatureDelegation.STATUS_NEEDS_INPUT,
            pending_question="Which database?",
            pending_options=["Postgres", "SQLite"],
        )
        CodingChatWaitService.watch_delegation(chat=self.chat, delegation=delegation)
        message = ChatMessage.objects.get(chat=self.chat, metadata__event="needs_input")
        self.assertIn("Database choice", message.text)
        self.assertIn("SQLite", message.text)


class DefaultDelegationWaitTests(TestCase):
    def setUp(self):
        self.machine = SshMachine.objects.create(name="Default wait machine", host="wait-default.example", username="dev", auth_type=SshMachine.AUTH_AGENT, allow_ai_commands=True)
        self.session = CodingSession.objects.create(name="Default wait session", machine=self.machine, remote_working_directory="/work")

    @patch("orchestration.tools.coding_sessions._wait_for_turn", return_value={})
    @patch("orchestration.tools.coding_sessions.CodingSessionService.start_turn")
    def test_task_delegation_waits_by_default_without_explicit_parameter(self, start_turn, _wait):
        from orchestration.tools.coding_sessions import delegate_task
        turn = CodingTurn.objects.create(session=self.session, prompt="Inspect", status=CodingTurn.STATUS_RUNNING)
        start_turn.return_value = turn
        result = delegate_task(str(self.session.pk), "Inspect")
        self.assertTrue(result["wait_for_completion"])


class FlexibleCallDelegationWaitTests(TestCase):
    def setUp(self):
        self.machine = SshMachine.objects.create(name="Call machine", host="call.example", username="dev", auth_type=SshMachine.AUTH_AGENT, allow_ai_commands=True)
        self.first_session = CodingSession.objects.create(name="First worker", machine=self.machine, remote_working_directory="/one")
        self.second_session = CodingSession.objects.create(name="Second worker", machine=self.machine, remote_working_directory="/two")
        self.call = CallSession.objects.create(goal="Delegate work", status=CallSession.STATUS_IN_CALL)

    def test_call_tracks_concurrent_delegations_and_switches_wait_independently(self):
        first = CodingTurn.objects.create(session=self.first_session, prompt="First", status=CodingTurn.STATUS_RUNNING)
        second = CodingTurn.objects.create(session=self.second_session, prompt="Second", status=CodingTurn.STATUS_RUNNING)
        first_watch = CodingChatWaitService.watch_turn(call_session=self.call, turn=first, waiting=True)
        second_watch = CodingChatWaitService.watch_turn(call_session=self.call, turn=second, waiting=False)

        state = CodingChatWaitService.list_for_origin(call_session=self.call)
        self.assertEqual(state["active_count"], 2)
        self.assertTrue(state["waiting"])
        self.assertEqual(sum(item["waiting"] for item in state["delegations"]), 1)

        CodingChatWaitService.set_wait(call_session=self.call, selector=str(first_watch.pk), waiting=False)
        CodingChatWaitService.set_wait(call_session=self.call, selector=str(second_watch.pk), waiting=True)
        state = CodingChatWaitService.list_for_origin(call_session=self.call)
        waiting_ids = {item["watch_id"] for item in state["delegations"] if item["waiting"]}
        self.assertEqual(waiting_ids, {str(second_watch.pk)})

    def test_call_delegation_endpoint_lists_wait_state_and_updates(self):
        from orchestration.views import call_delegation_state
        turn = CodingTurn.objects.create(session=self.first_session, prompt="Search", status=CodingTurn.STATUS_RUNNING)
        CodingChatWaitService.watch_turn(call_session=self.call, turn=turn, waiting=True)
        state = call_delegation_state(None, self.call.pk)
        self.assertTrue(state["waiting"])
        self.assertEqual(state["active_count"], 1)
        self.assertEqual(state["delegations"][0]["session_name"], "First worker")
        self.assertEqual(state["updates"], [])

    def test_waiting_call_receives_completion_as_transcript_update(self):
        turn = CodingTurn.objects.create(session=self.first_session, prompt="Search", status=CodingTurn.STATUS_RUNNING)
        CodingChatWaitService.watch_turn(call_session=self.call, turn=turn, waiting=True)
        turn.status = CodingTurn.STATUS_COMPLETED
        turn.summary = "Found ExamSense."
        turn.save(update_fields=["status", "summary"])
        CodingChatWaitService.publish_for_session(self.first_session)
        update = CallTranscriptEntry.objects.get(session=self.call, content__startswith="[Delegation update:")
        self.assertIn("Found ExamSense", update.content)

    def test_nonwaiting_completion_is_tracked_without_interrupting_call(self):
        turn = CodingTurn.objects.create(session=self.first_session, prompt="Search", status=CodingTurn.STATUS_COMPLETED, summary="Done")
        watch = CodingChatWaitService.watch_turn(call_session=self.call, turn=turn, waiting=False)
        watch.refresh_from_db()
        self.assertFalse(watch.active)
        self.assertFalse(CallTranscriptEntry.objects.filter(session=self.call, content__startswith="[Delegation update:").exists())

    @patch("orchestration.services.FunctionRegistry.resolve_callable")
    def test_call_runner_registers_delegation_without_chat_job(self, resolve):
        turn = CodingTurn.objects.create(session=self.first_session, prompt="Search", status=CodingTurn.STATUS_RUNNING)
        resolve.return_value = lambda **_params: {"delegated_turn_id": str(turn.pk), "wait_for_completion": True}
        result = FunctionRunnerService.run_function_call(
            FunctionCallPayload(trace_id="call-wait", function_id="coding_sessions.delegate_task", params={}),
            call_session=self.call,
        )
        self.assertEqual(result.status, "ok")
        self.assertTrue(CodingDelegationWatch.objects.filter(call_session=self.call, turn=turn, waiting=True).exists())
