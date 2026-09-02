from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from ninja.testing import TestClient

from orchestration.registry import FunctionRegistry
from workout.models import Exercise, WorkoutGoal, WorkoutPlan, WorkoutSession
from workout.services import active_sessions, dashboard, delete_exercise, delete_plan, finish_session, log_session, resolve_exercise, save_plan, start_session, update_session_item
from workout.views import router


class WorkoutServiceTests(TestCase):
    def test_plan_import_resolves_alias_and_creates_missing_exercise(self):
        squat, _ = resolve_exercise("Back Squat", defaults={"aliases": ["squat"]})
        result = save_plan(
            title="Imported strength",
            source="import",
            exercises=[
                {"name": "SQUAT", "sets": 5, "reps": "5"},
                {"name": "Farmer Carry", "sets": 3, "duration_seconds": 45},
            ],
        )
        self.assertEqual(WorkoutPlan.objects.count(), 1)
        self.assertEqual(result["exercises"][0]["exercise"]["id"], str(squat.id))
        self.assertEqual(result["created_exercises"], ["Farmer Carry"])
        self.assertEqual(Exercise.objects.count(), 2)

    def test_session_logging_reuses_known_and_creates_missing_with_metadata(self):
        known, _ = resolve_exercise("Bench Press")
        started = timezone.now() - timedelta(minutes=50)
        result = log_session(
            title="Push day",
            started_at=started.isoformat(),
            ended_at=(started + timedelta(minutes=40)).isoformat(),
            metadata={"location": "garage"},
            exercises=[
                {"name": "bench-press", "sets": 3, "reps": 8, "weight_kg": 72.5, "rpe": 8},
                {"name": "Plank", "duration_seconds": 90, "metadata": {"side": "front"}},
            ],
        )
        self.assertEqual(WorkoutSession.objects.count(), 1)
        self.assertEqual(result["duration_seconds"], 2400)
        self.assertEqual(result["metadata"]["location"], "garage")
        self.assertEqual(result["exercises"][0]["exercise"]["id"], str(known.id))
        self.assertEqual(result["exercises"][0]["weight_kg"], 72.5)
        self.assertEqual(result["created_exercises"], ["Plank"])

    def test_progress_series_consistency_and_goal(self):
        today = timezone.now()
        for days_ago, weight in ((0, 80), (1, 77.5), (3, 75)):
            log_session(started_at=(today - timedelta(days=days_ago)).isoformat(), exercises=[{"name": "Deadlift", "sets": 3, "reps": 5, "weight_kg": weight}])
        exercise = Exercise.objects.get(normalized_name="deadlift")
        WorkoutGoal.objects.create(title="Three weekly sessions", metric="sessions_per_week", target_value=3, unit="sessions")
        WorkoutGoal.objects.create(title="Pull 100 kg", metric="exercise_weight_kg", target_value=100, unit="kg", exercise=exercise)
        result = dashboard(days=30, exercise="deadlift")
        self.assertEqual(result["session_count"], 3)
        self.assertEqual(result["current_streak_days"], 2)
        self.assertEqual(len(result["daily"]), 30)
        self.assertEqual(len(result["weekly"]), 12)
        self.assertEqual(max(x["weight_kg"] for x in result["exercise_trend"]), 80)
        self.assertEqual(len(result["goals"]), 2)

    def test_invalid_rep_range_is_rejected_for_completed_log(self):
        with self.assertRaisesMessage(ValueError, "whole number"):
            log_session(exercises=[{"name": "Squat", "reps": "8-10"}])
        self.assertEqual(WorkoutSession.objects.count(), 0)


class WorkoutApiAndActionTests(TestCase):
    def setUp(self):
        self.client = TestClient(router)

    def test_api_end_to_end(self):
        plan = self.client.post("/plans", json={"title": "API plan", "source": "import", "exercises": [{"name": "Goblet Squat", "sets": 3, "reps": "10"}]})
        self.assertEqual(plan.status_code, 200)
        logged = self.client.post("/sessions", json={"title": "API workout", "plan": plan.json()["id"], "exercises": [{"name": "Goblet Squat", "sets": 3, "reps": 10, "weight_kg": 24}]})
        self.assertEqual(logged.status_code, 200)
        history = self.client.get("/sessions")
        progress = self.client.get("/dashboard?days=30&exercise=Goblet%20Squat")
        self.assertEqual(len(history.json()["sessions"]), 1)
        self.assertEqual(progress.json()["session_count"], 1)
        self.assertEqual(progress.json()["exercise_trend"][0]["weight_kg"], 24)

    def test_registered_actions_expose_history_and_progress(self):
        import orchestration.tools.workout  # noqa: F401
        logger = FunctionRegistry.resolve_callable("workout.log_session")
        reader = FunctionRegistry.resolve_callable("workout.get_history")
        progress = FunctionRegistry.resolve_callable("workout.get_progress")
        logger(exercises=[{"name": "Run", "duration_seconds": 1200, "distance_km": 3.1}])
        self.assertEqual(reader()["sessions"][0]["exercises"][0]["distance_km"], 3.1)
        self.assertEqual(progress(days=14)["session_count"], 1)


class WorkoutLlmResolutionGuidanceTests(TestCase):
    def test_persisted_tool_guidance_requires_llm_directory_review(self):
        from orchestration.models import ToolFunction, ToolModule
        module = ToolModule.objects.get(slug="workout")
        logger = ToolFunction.objects.get(manifest_id="workout.log_session")
        self.assertIn("LLM must inspect workout.list_exercises first", module.caller_instructions)
        self.assertIn("semantic", module.caller_instructions)
        self.assertIn("LLM judgment", logger.description)


class WorkoutSessionDeletionTests(TestCase):
    def setUp(self):
        self.client = TestClient(router)

    def test_api_deletes_exact_session_and_preserves_other_sessions(self):
        first = log_session(title="Delete me", exercises=[{"name": "Row", "reps": 8}])
        keep = log_session(title="Keep me", exercises=[{"name": "Row", "reps": 10}])
        response = self.client.delete(f"/sessions/{first['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(WorkoutSession.objects.filter(pk=first["id"]).exists())
        self.assertTrue(WorkoutSession.objects.filter(pk=keep["id"]).exists())

    def test_action_deletes_session_and_missing_id_fails_safely(self):
        import orchestration.tools.workout  # noqa: F401
        item = log_session(title="Action delete", exercises=[{"name": "Run", "duration_seconds": 60}])
        remover = FunctionRegistry.resolve_callable("workout.delete_session")
        self.assertTrue(remover(item["id"])["deleted"])
        with self.assertRaisesMessage(ValueError, "not found"):
            remover(item["id"])


class ActiveWorkoutSessionTests(TestCase):
    def setUp(self):
        self.client = TestClient(router)

    def test_start_plan_check_items_and_finish_lifecycle(self):
        plan = save_plan(title="Live plan", exercises=[{"name":"Squat","sets":3,"reps":"8-10"},{"name":"Plank","duration_seconds":60}])
        session = start_session(plan=plan["id"])
        self.assertEqual(session["status"], "active")
        self.assertEqual(len(session["exercises"]), 2)
        self.assertFalse(session["exercises"][0]["completed"])
        self.assertEqual(session["exercises"][0]["metadata"]["prescribed_reps"], "8-10")
        changed = update_session_item(session["exercises"][0]["id"], completed=True, reps=9, weight_kg=70)
        self.assertTrue(changed["completed"])
        self.assertEqual(changed["reps"], 9)
        self.assertEqual(changed["weight_kg"], 70)
        self.assertEqual(len(active_sessions()), 1)
        result = finish_session(session["id"])
        self.assertEqual(result["status"], "completed")
        self.assertIsNotNone(result["ended_at"])
        self.assertEqual(active_sessions(), [])

    def test_active_session_api_end_to_end(self):
        started = self.client.post("/sessions/start", json={"title":"Today's workout","exercises":[{"name":"Pull Up","sets":3,"reps":5}]})
        self.assertEqual(started.status_code, 200)
        body = started.json()
        active = self.client.get("/sessions/active")
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["sessions"][0]["id"], body["id"])
        item_id = body["exercises"][0]["id"]
        checked = self.client.patch(f"/sessions/items/{item_id}", json={"completed":True,"reps":6})
        self.assertTrue(checked.json()["completed"])
        finished = self.client.post(f"/sessions/{body['id']}/finish", json={})
        self.assertEqual(finished.json()["status"], "completed")

    def test_registered_actions_support_active_workout(self):
        import orchestration.tools.workout  # noqa: F401
        starter = FunctionRegistry.resolve_callable("workout.start_session")
        active = FunctionRegistry.resolve_callable("workout.get_active_sessions")
        updater = FunctionRegistry.resolve_callable("workout.update_session_item")
        finisher = FunctionRegistry.resolve_callable("workout.finish_session")
        session = starter(exercises=[{"name":"Lunge","sets":2,"reps":8}])
        self.assertEqual(active()["sessions"][0]["id"], session["id"])
        self.assertTrue(updater(session["exercises"][0]["id"], completed=True)["completed"])
        self.assertEqual(finisher(session["id"])["status"], "completed")

    def test_completed_history_logs_remain_completed(self):
        result = log_session(exercises=[{"name":"Walk","duration_seconds":600}])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["exercises"][0]["completed"])


class WorkoutPlanAndExerciseDeletionTests(TestCase):
    def setUp(self): self.client=TestClient(router)

    def test_delete_plan_preserves_linked_session(self):
        plan=save_plan(title="Disposable plan",exercises=[{"name":"Press","sets":3,"reps":5}])
        session=log_session(plan=plan["id"],exercises=[{"name":"Press","sets":3,"reps":5}])
        result=delete_plan(plan["id"])
        self.assertTrue(result["deleted"]); self.assertEqual(result["preserved_sessions"],1)
        preserved=WorkoutSession.objects.get(pk=session["id"])
        self.assertIsNone(preserved.plan_id)

    def test_exercise_delete_requires_explicit_reference_removal(self):
        session=log_session(exercises=[{"name":"Burpee","reps":10}])
        exercise=Exercise.objects.get(normalized_name="burpee")
        with self.assertRaisesMessage(ValueError,"explicitly allow"):
            delete_exercise(exercise.id)
        result=delete_exercise(exercise.id,force=True)
        self.assertEqual(result["deleted_log_entries"],1)
        self.assertFalse(Exercise.objects.filter(pk=exercise.id).exists())
        self.assertTrue(WorkoutSession.objects.filter(pk=session["id"]).exists())

    def test_plan_and_exercise_delete_api(self):
        plan=self.client.post("/plans",json={"title":"API delete plan","exercises":[{"name":"API movement"}]}).json()
        self.assertEqual(self.client.delete(f"/plans/{plan['id']}").status_code,200)
        exercise=Exercise.objects.get(normalized_name="api movement")
        response=self.client.delete(f"/exercises/{exercise.id}")
        self.assertEqual(response.status_code,200)

    def test_registered_delete_actions(self):
        import orchestration.tools.workout  # noqa: F401
        plan=save_plan(title="Action plan",exercises=[{"name":"Action movement"}])
        remove_plan=FunctionRegistry.resolve_callable("workout.delete_plan")
        remove_exercise=FunctionRegistry.resolve_callable("workout.delete_exercise")
        self.assertTrue(remove_plan(plan["id"])["deleted"])
        exercise=Exercise.objects.get(normalized_name="action movement")
        self.assertTrue(remove_exercise(str(exercise.id))["deleted"])
