import json
from datetime import timedelta
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.utils import timezone

from orchestration.models import Objective, ObjectiveTask, SoftEvent, SoftEventObjective, SoftEventSlot
from orchestration.two_week_planner import TwoWeekPlannerService
from orchestration.views import delete_objective, update_objective

class ObjectiveManagementTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.root = Objective.objects.create(title="Root")
        self.child = Objective.objects.create(title="Child", parent=self.root)
        self.task = ObjectiveTask.objects.create(objective=self.child, title="Task")

    def test_root_delete_cascades_tree_and_generated_sessions(self):
        event = SoftEvent.objects.create(
            title="Generated work",
            metadata={"source": "objective_scheduler"},
        )
        SoftEventObjective.objects.create(soft_event=event, objective=self.child)
        SoftEventSlot.objects.create(
            soft_event=event,
            start_at=timezone.now() + timedelta(hours=1),
            end_at=timezone.now() + timedelta(hours=2),
        )

        response = delete_objective(self.factory.delete("/"), self.root.id)

        self.assertTrue(response["ok"])
        self.assertEqual(response["deleted_objectives"], 2)
        self.assertEqual(response["deleted_tasks"], 1)
        self.assertFalse(Objective.objects.filter(id=self.root.id).exists())
        self.assertFalse(SoftEvent.objects.filter(id=event.id).exists())

    def test_objective_cannot_move_below_its_descendant(self):
        request = self.factory.patch(
            "/",
            data=json.dumps({"parent_id": str(self.child.id)}),
            content_type="application/json",
        )
        with self.assertRaisesMessage(Exception, "descendants"):
            update_objective(request, self.root.id)


class UnifiedTwoWeekPlannerTests(TestCase):
    def setUp(self):
        self.start = timezone.now().replace(second=0, microsecond=0)
        self.end = self.start + timedelta(days=14)
        self.objective = Objective.objects.create(title="Ship feature", priority=8)
        self.urgent = ObjectiveTask.objects.create(
            objective=self.objective,
            title="Finish implementation",
            due_at=self.start + timedelta(days=5),
            estimated_effort_minutes=90,
            remaining_effort_minutes=90,
        )
        self.later = ObjectiveTask.objects.create(
            objective=self.objective,
            title="Later cleanup",
            due_at=self.start + timedelta(days=30),
        )
        self.soft_event_id = "a6c85bbb-8f12-4850-821c-b9ddb43868d8"
        self.soft_state = {
            "soft_events": [
                {
                    "id": self.soft_event_id,
                    "title": "Exercise",
                    "preferred_duration_minutes": 60,
                    "min_duration_minutes": 30,
                    "soft_deadline": None,
                    "hard_deadline": None,
                    "priority": 2,
                }
            ],
            "slots": [],
        }

    def test_single_response_plans_urgent_objectives_and_flexible_events(self):
        session_start = self.start + timedelta(days=1, hours=2)
        soft_start = self.start + timedelta(days=1, hours=5)
        response = {
            "objective_sessions": [
                {
                    "objective_id": str(self.objective.id),
                    "task_ids": [str(self.urgent.id)],
                    "title": "Finish implementation",
                    "description": "Complete the feature",
                    "notes": "",
                    "priority": 8,
                    "start_at": session_start.isoformat(),
                    "end_at": (session_start + timedelta(minutes=90)).isoformat(),
                    "notify_at": None,
                    "rationale": "Early deadline coverage",
                }
            ],
            "soft_event_slots": [
                {
                    "soft_event_id": self.soft_event_id,
                    "start_at": soft_start.isoformat(),
                    "end_at": (soft_start + timedelta(minutes=60)).isoformat(),
                    "notify_at": None,
                    "rationale": "Free afternoon",
                }
            ],
            "summary": "Balanced plan",
        }
        with patch.object(TwoWeekPlannerService, "_request", return_value=(response, "test-model")) as request:
            sessions, actions, _trace_id, summary = TwoWeekPlannerService.plan(
                objectives=[self.objective],
                hard_events=[],
                soft_state=self.soft_state,
                window_start=self.start,
                window_end=self.end,
            )

        request.assert_called_once()
        payload = request.call_args.args[0]
        self.assertEqual(len(payload["objectives"]), 1)
        self.assertEqual([task["id"] for task in payload["objectives"][0]["tasks"]], [str(self.urgent.id)])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(actions), 1)
        self.assertEqual(summary, "Balanced plan")

    def test_invalid_or_incomplete_plan_is_rejected_before_application(self):
        response = {"objective_sessions": [], "soft_event_slots": [], "summary": ""}
        with patch.object(TwoWeekPlannerService, "_request", return_value=(response, "test-model")):
            with self.assertRaisesMessage(ValueError, "Uncovered urgent task"):
                TwoWeekPlannerService.plan(
                    objectives=[self.objective],
                    hard_events=[],
                    soft_state=self.soft_state,
                    window_start=self.start,
                    window_end=self.end,
                )

    def test_partial_effort_plan_is_rejected(self):
        session_start = self.start + timedelta(days=1, hours=2)
        response = {
            "objective_sessions": [
                {
                    "objective_id": str(self.objective.id),
                    "task_ids": [str(self.urgent.id)],
                    "title": "Too-short implementation block",
                    "start_at": session_start.isoformat(),
                    "end_at": (session_start + timedelta(minutes=30)).isoformat(),
                }
            ],
            "soft_event_slots": [],
            "summary": "",
        }
        with patch.object(TwoWeekPlannerService, "_request", return_value=(response, "test-model")):
            with self.assertRaisesMessage(ValueError, "30/90 minutes"):
                TwoWeekPlannerService.plan(
                    objectives=[self.objective],
                    hard_events=[],
                    soft_state={"soft_events": [], "slots": []},
                    window_start=self.start,
                    window_end=self.end,
                )
