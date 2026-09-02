from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase
from django.utils import timezone
from datetime import timedelta

from orchestration.call_processing import (
    complete_call,
    create_call_session,
    execute_call_action,
    mark_call_missed,
    notify_incoming_call,
    poll_call_sessions,
    process_call_actions,
)
from orchestration.models import CallSession, UserMessage
from coding.models import CodingDelegationWatch, CodingSession, CodingTurn
from ssh_connections.models import SshMachine
from orchestration.views import (
    add_transcript_entry,
    create_call,
    get_settings,
    list_call_sessions,
    preview_call_voice,
    create_realtime_token,
    set_settings,
)
from orchestration.services import ModelConfigService, PersonaService
from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.schemas import FunctionResultPayload
from orchestration.schemas import FunctionResultPayload
from orchestration.schemas import FunctionResultPayload


class RealtimeCallActionTests(TestCase):
    def test_executes_action_and_records_audio_friendly_result(self):
        session = CallSession.objects.create(
            goal="Organize my day", status=CallSession.STATUS_IN_CALL
        )
        decisions = [
            {"call": {"function_id": "calendar.create", "params": {"title": "Focus"}}},
            {"done": True, "summary": "I added the focus block to your calendar."},
        ]
        with patch("orchestration.call_processing.ModuleDirectory.function_catalog", return_value=[]), patch(
            "orchestration.call_processing._plan_with_no_clarifications", side_effect=decisions
        ), patch(
            "orchestration.call_processing.FunctionRunnerService.run_function_call",
            return_value=FunctionResultPayload(trace_id="test", call_id="test", status="ok", data={"created": True}),
        ) as runner:
            result = execute_call_action(session, "Add a focus block")

        self.assertEqual(result, "I added the focus block to your calendar.")
        runner.assert_called_once()
        session.refresh_from_db()
        self.assertEqual(session.status, CallSession.STATUS_IN_CALL)
        entry = session.transcript_entries.get(role="system")
        self.assertEqual(entry.content, f"Action result: {result}")

    def test_delegation_immediately_returns_truthful_waiting_reply(self):
        session = CallSession.objects.create(goal="Find a project", status=CallSession.STATUS_IN_CALL)
        machine = SshMachine.objects.create(name="Animus", host="animus.test", username="dev", auth_type=SshMachine.AUTH_AGENT, allow_ai_commands=True)
        coding_session = CodingSession.objects.create(name="Find ExamSense", machine=machine)
        turn = CodingTurn.objects.create(session=coding_session, prompt="Find ExamSense", status=CodingTurn.STATUS_RUNNING)

        def run_delegation(*_args, **_kwargs):
            CodingDelegationWatch.objects.create(call_session=session, session=coding_session, turn=turn, waiting=True)
            return FunctionResultPayload(trace_id="test", call_id="test", status="ok", data={"delegated_turn_id": str(turn.id), "wait_for_completion": True})

        with patch("orchestration.call_processing.ModuleDirectory.function_catalog", return_value=[]), patch(
            "orchestration.call_processing._plan_with_no_clarifications",
            return_value={"call": {"function_id": "coding_sessions.delegate_task", "params": {}}},
        ) as planner, patch(
            "orchestration.call_processing.FunctionRunnerService.run_function_call",
            side_effect=run_delegation,
        ):
            result = execute_call_action(session, "Find ExamSense")

        self.assertIn("Codex is working", result)
        self.assertIn("waiting for it to finish", result)
        self.assertIn("Find ExamSense", result)
        planner.assert_called_once()
        self.assertEqual(session.transcript_entries.get(role="system").content, f"Action result: {result}")

    def test_planner_parse_failure_falls_back_to_active_wait(self):
        session = CallSession.objects.create(goal="Find a project", status=CallSession.STATUS_IN_CALL)
        machine = SshMachine.objects.create(name="Animus", host="animus.test", username="dev", auth_type=SshMachine.AUTH_AGENT, allow_ai_commands=True)
        coding_session = CodingSession.objects.create(name="Find ExamSense", machine=machine)
        turn = CodingTurn.objects.create(session=coding_session, prompt="Find ExamSense", status=CodingTurn.STATUS_RUNNING)
        CodingDelegationWatch.objects.create(call_session=session, session=coding_session, turn=turn, waiting=True)

        with patch("orchestration.call_processing.ModuleDirectory.function_catalog", return_value=[]), patch(
            "orchestration.call_processing._plan_with_no_clarifications",
            return_value={"done": True, "summary": "Planner output could not be parsed."},
        ):
            result = execute_call_action(session, "Check the task")

        self.assertIn("Codex is working", result)
        self.assertNotIn("could not be parsed", result)

    def test_rejects_empty_action_without_running_tools(self):
        session = CallSession.objects.create(goal="Help", status=CallSession.STATUS_IN_CALL)
        with patch("orchestration.call_processing.FunctionRunnerService.run_function_call") as runner:
            result = execute_call_action(session, "  ")
        self.assertIn("empty", result)
        runner.assert_not_called()


class CallOriginIsolationTests(TestCase):
    @patch("orchestration.call_processing.notify_incoming_call")
    def test_browser_headers_identify_web_call_without_query_flag(self, notify):
        request = RequestFactory().post(
            "/api/orchestration/call_sessions?goal=Browser",
            HTTP_ORIGIN="https://corv.example",
            HTTP_REFERER="https://corv.example/calls",
        )

        response = create_call(request, goal="Browser")

        session = CallSession.objects.get(id=response.id)
        self.assertEqual(session.metadata["origin"], "web")
        notify.assert_not_called()

    @patch("orchestration.call_processing.mark_call_missed")
    def test_ringing_timeout_ignores_web_calls(self, mark_missed):
        old = timezone.now() - timedelta(minutes=2)
        web = CallSession.objects.create(
            goal="Slow browser connection",
            status=CallSession.STATUS_RINGING,
            ringing_started_at=old,
            metadata={"origin": "web"},
        )
        mobile = CallSession.objects.create(
            goal="Unanswered mobile call",
            status=CallSession.STATUS_RINGING,
            ringing_started_at=old,
            metadata={"origin": "mobile"},
        )
        legacy = CallSession.objects.create(
            goal="Legacy unanswered call",
            status=CallSession.STATUS_RINGING,
            ringing_started_at=old,
        )

        poll_call_sessions(ring_timeout_seconds=45)

        missed_ids = {str(call.args[0].id) for call in mark_missed.call_args_list}
        self.assertNotIn(str(web.id), missed_ids)
        self.assertIn(str(mobile.id), missed_ids)
        self.assertIn(str(legacy.id), missed_ids)

    @patch("orchestration.call_processing.notify_incoming_call")
    def test_immediate_web_call_does_not_send_incoming_notification(self, notify):
        session = create_call_session("Web conversation", origin="web")

        self.assertEqual(session.status, CallSession.STATUS_RINGING)
        self.assertEqual(session.metadata["origin"], "web")
        notify.assert_not_called()

    @patch("orchestration.call_processing.send_call_push_to_all")
    def test_notification_guard_blocks_web_session(self, send_push):
        session = CallSession.objects.create(
            goal="Web conversation",
            status=CallSession.STATUS_RINGING,
            metadata={"origin": "web"},
        )

        notify_incoming_call(session)

        send_push.assert_not_called()

    @patch("orchestration.call_processing.send_call_push_to_all")
    def test_mobile_call_preserves_incoming_notification(self, send_push):
        session = create_call_session("Mobile conversation", origin="mobile")

        self.assertEqual(session.metadata["origin"], "mobile")
        send_push.assert_called_once()

    @patch("orchestration.call_processing.send_message_push_to_all")
    @patch("orchestration.call_processing.ChatAIService.phrase_inbox_message")
    def test_missed_web_call_has_no_mobile_follow_up(self, phrase, send_push):
        session = CallSession.objects.create(
            goal="Web conversation",
            status=CallSession.STATUS_RINGING,
            metadata={"origin": "web"},
        )

        mark_call_missed(session)

        session.refresh_from_db()
        self.assertEqual(session.status, CallSession.STATUS_MISSED)
        self.assertFalse(UserMessage.objects.exists())
        phrase.assert_not_called()
        send_push.assert_not_called()

    def test_mobile_session_listing_excludes_web_calls(self):
        web = CallSession.objects.create(
            goal="Web conversation", status=CallSession.STATUS_RINGING, metadata={"origin": "web"}
        )
        mobile = CallSession.objects.create(
            goal="Mobile conversation", status=CallSession.STATUS_RINGING, metadata={"origin": "mobile"}
        )
        legacy = CallSession.objects.create(
            goal="Legacy scheduled conversation", status=CallSession.STATUS_RINGING
        )

        result = list_call_sessions(None, platform="mobile")
        ids = {str(item.id) for item in result}

        self.assertNotIn(str(web.id), ids)
        self.assertIn(str(mobile.id), ids)
        self.assertIn(str(legacy.id), ids)


class FrozenFollowUpCallTests(TestCase):
    @patch("orchestration.call_processing._plan_with_no_clarifications")
    def test_follow_up_planner_is_frozen_even_when_called_directly(self, planner):
        session = CallSession.objects.create(
            goal="User initiated call", status=CallSession.STATUS_COMPLETED
        )

        result = process_call_actions(session)

        self.assertEqual(result, [])
        planner.assert_not_called()

    @patch("orchestration.call_processing.process_call_actions")
    @patch("orchestration.call_processing.summarize_call")
    def test_completing_call_does_not_enter_follow_up_flow(self, summarize, follow_up):
        session = CallSession.objects.create(
            goal="User initiated call", status=CallSession.STATUS_IN_CALL
        )

        complete_call(session)

        session.refresh_from_db()
        self.assertEqual(session.status, CallSession.STATUS_COMPLETED)
        summarize.assert_called_once_with(session)
        follow_up.assert_not_called()

    @patch("orchestration.views.should_end_call")
    def test_assistant_result_does_not_automatically_end_active_call(self, should_end):
        session = CallSession.objects.create(
            goal="Run an action", status=CallSession.STATUS_IN_CALL
        )

        response = add_transcript_entry(
            None, session.id, role="assistant", content="The action completed successfully."
        )

        session.refresh_from_db()
        self.assertEqual(session.status, CallSession.STATUS_IN_CALL)
        self.assertFalse(response.end_call)
        should_end.assert_not_called()


class CallPersonalityTests(TestCase):
    @patch("orchestration.views.corv_settings.openai_key", "test-key")
    @patch("orchestration.views.PersonaService.build_persona_prompt", return_value="Custom Corv persona")
    @patch("orchestration.views.httpx.Client")
    def test_realtime_call_uses_shared_persona_and_compact_witty_voice(self, client_class, _persona):
        session = CallSession.objects.create(goal="Talk", status=CallSession.STATUS_IN_CALL)
        client = client_class.return_value.__enter__.return_value
        client.post.return_value.raise_for_status.return_value = None
        client.post.return_value.json.return_value = {"value": "secret"}

        create_realtime_token(None, session.id)

        instructions = client.post.call_args.kwargs["json"]["session"]["instructions"]
        self.assertIn("Custom Corv persona", instructions)
        self.assertIn("one short sentence", instructions)
        self.assertIn("dry-witty", instructions)
        self.assertIn("rather than polished or generic", instructions.lower())
        self.assertIn("full action capabilities", instructions)
        self.assertIn("actively try the relevant available actions", instructions)
        self.assertIn("cannot do something", instructions)
        self.assertIn("genuinely exhausted", instructions)

    @patch("orchestration.services.UserInfoService.format_core_profile_block", return_value="")
    @patch("orchestration.services.PersonaService.get_persona", return_value=None)
    def test_shared_persona_enforces_concise_non_generic_voice(self, _persona, _profile):
        prompt = PersonaService.build_persona_prompt()

        self.assertIn("one or two compact sentences", prompt)
        self.assertIn("dry-witty", prompt)
        self.assertIn("avoid generic filler", prompt)


class CallVoiceSettingsTests(TestCase):
    def test_voice_setting_has_multiple_options_and_persists(self):
        request = RequestFactory().post(
            "/api/orchestration/settings",
            data='{"call_voice":"cedar"}',
            content_type="application/json",
        )

        updated = set_settings(request)
        current = get_settings(RequestFactory().get("/api/orchestration/settings"))

        self.assertEqual(updated["call_voice"], "cedar")
        self.assertEqual(current["call_voice"], "cedar")
        self.assertGreaterEqual(len(current["call_voice_options"]), 5)
        self.assertIn("marin", current["call_voice_options"])
        self.assertIn("cedar", current["call_voice_options"])

    @patch("orchestration.views.corv_settings.openai_key", "test-key")
    @patch("orchestration.views.httpx.post")
    def test_voice_preview_returns_playable_audio(self, post):
        response = post.return_value
        response.content = b"preview-mp3"
        response.raise_for_status.return_value = None

        result = preview_call_voice(None, "marin")

        self.assertEqual(result["content_type"], "audio/mpeg")
        self.assertTrue(result["audio_base64"])
        self.assertEqual(post.call_args.kwargs["json"]["voice"], "marin")

    def test_invalid_voice_is_rejected_without_changing_setting(self):
        ModelConfigService.set_setting("call_voice", "marin")
        request = RequestFactory().post(
            "/api/orchestration/settings",
            data='{"call_voice":"not-a-voice"}',
            content_type="application/json",
        )

        with self.assertRaises(Exception):
            set_settings(request)

        self.assertEqual(ModelConfigService.get_call_voice(), "marin")


class FunctionCallerSharedContextTests(TestCase):
    @patch("orchestration.function_caller.PersonaService.build_persona_prompt", return_value="Core user profile: The user's name is Tudor.")
    @patch("orchestration.function_caller.get_client")
    @patch("orchestration.function_caller.resolve_provider", return_value="openai")
    def test_planner_receives_frontman_user_context(self, _provider, get_client, _persona):
        client = MagicMock()
        client.responses.create.return_value = SimpleNamespace(output_text='{"done": true, "summary": "ok"}', usage=None)
        get_client.return_value = client
        FunctionCallOrchestrator._plan_next_action(user_request="Make a PDF with my name", tool_catalog=[], prior_results=[])
        developer_text = client.responses.create.call_args.kwargs["input"][0]["content"][0]["text"]
        self.assertIn("Shared Frontman context", developer_text)
        self.assertIn("The user's name is Tudor.", developer_text)
