from unittest.mock import patch

from django.test import TestCase

from coding.models import CodingSession, CodingTurn, FeatureDelegation
from coding.services import CodingSessionService
from ssh_connections.models import SshMachine


class AbortDelegationTests(TestCase):
    def setUp(self):
        machine = SshMachine.objects.create(
            name="Abort target",
            host="abort.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        self.session = CodingSession.objects.create(
            name="Abort session", machine=machine, status=CodingSession.STATUS_RUNNING
        )

    def test_aborting_turn_keeps_session_ready_and_history_cancelled(self):
        turn = CodingTurn.objects.create(
            session=self.session,
            prompt="Abort this work",
            source=CodingTurn.SOURCE_UI,
            status=CodingTurn.STATUS_RUNNING,
        )
        with patch.object(
            CodingSessionService,
            "cancel_turn",
            wraps=CodingSessionService.cancel_turn,
        ) as cancel:
            payload = CodingSessionService.abort_delegation(self.session)

        turn.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(turn.status, CodingTurn.STATUS_CANCELLED)
        self.assertEqual(self.session.status, CodingSession.STATUS_READY)
        self.assertEqual(payload["status"], CodingSession.STATUS_READY)
        cancel.assert_called_once()

    def test_paused_delegation_can_be_aborted(self):
        self.session.status = CodingSession.STATUS_NEEDS_INPUT
        self.session.pending_question = "Choose an implementation"
        self.session.save(update_fields=["status", "pending_question", "updated_at"])
        turn = CodingTurn.objects.create(
            session=self.session,
            prompt="Paused work",
            source=CodingTurn.SOURCE_UI,
            status=CodingTurn.STATUS_NEEDS_INPUT,
            question="Choose an implementation",
        )
        payload = CodingSessionService.abort_delegation(self.session)
        turn.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(turn.status, CodingTurn.STATUS_CANCELLED)
        self.assertEqual(self.session.pending_question, "")
        self.assertEqual(payload["status"], CodingSession.STATUS_READY)

    @patch("coding.delegations.FeatureDelegationService._notify")
    def test_aborting_feature_delegation_stops_it(self, _notify):
        delegation = FeatureDelegation.objects.create(
            session=self.session,
            title="Abort feature",
            description="Work in progress",
            acceptance_criteria=["Done"],
            status=FeatureDelegation.STATUS_CODING,
        )
        CodingSessionService.abort_delegation(self.session)
        delegation.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(delegation.status, FeatureDelegation.STATUS_STOPPED)
        self.assertEqual(self.session.status, CodingSession.STATUS_READY)

    def test_idle_session_is_rejected(self):
        self.session.status = CodingSession.STATUS_READY
        self.session.save(update_fields=["status", "updated_at"])
        with self.assertRaisesMessage(ValueError, "no active delegation"):
            CodingSessionService.abort_delegation(self.session)
