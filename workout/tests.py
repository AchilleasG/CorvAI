from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from PIL import Image

from django.test import TestCase, override_settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja.testing import TestClient

from orchestration.registry import FunctionRegistry
from workout.models import Exercise, WorkoutGoal, WorkoutPlan, WorkoutPlanExercise, WorkoutPlanSession, WorkoutSession
from workout.services import active_sessions, dashboard, delete_exercise, delete_plan, enrich_exercise, finish_session, log_session, resolve_exercise, save_plan, start_session, update_session_item
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


class ExerciseEnrichmentTests(TestCase):
    class Response:
        def __init__(self, *, data=None, content=b""): self._data=data; self.content=content
        def raise_for_status(self): return None
        def json(self): return self._data

    class Client:
        def __init__(self, catalog, image): self.catalog=catalog; self.image=image; self.calls=[]
        def get(self, url):
            self.calls.append(url)
            return ExerciseEnrichmentTests.Response(data=self.catalog) if url.endswith("exercises.json") else ExerciseEnrichmentTests.Response(content=self.image)

    def setUp(self):
        from workout import services
        self.client = TestClient(router)
        services._catalog_cache = None
        image=Image.new("RGB",(32,32),"white"); output=BytesIO(); image.save(output,"JPEG")
        self.catalog=[{"id":"Pushups","name":"Pushups","force":"push","level":"beginner","mechanic":"compound","equipment":"body only","primaryMuscles":["chest"],"secondaryMuscles":["triceps"],"category":"strength","instructions":["Keep a straight body line.","Lower and press."],"images":["Push-Up/0.jpg","Push-Up/1.jpg"]}]
        self.image=output.getvalue()

    def test_lazy_enrichment_persists_details_and_local_gif(self):
        exercise,_=resolve_exercise("Push Up")
        client=self.Client(self.catalog,self.image)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media,MEDIA_URL="/media/"):
            result=enrich_exercise(exercise.id,client=client)
            self.assertEqual(result["external_provider"],"free-exercise-db")
            self.assertEqual(result["enrichment_data"]["primary_muscles"],["chest"])
            self.assertTrue(result["demo_media_url"].endswith(".gif"))
            self.assertTrue((Path(media)/result["demo_media_url"].removeprefix("/media/")).exists())
            cached_client=self.Client([],b"")
            cached=enrich_exercise(exercise.id,client=cached_client)
            self.assertEqual(cached["external_id"],"Pushups")
            self.assertEqual(cached_client.calls,[])

    def test_detail_endpoint_and_action_return_enriched_record(self):
        exercise,_=resolve_exercise("Push Up")
        client=self.Client(self.catalog,self.image)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media,MEDIA_URL="/media/"):
            enrich_exercise(exercise.id,client=client)
            response=self.client.get(f"/exercises/{exercise.id}/details")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()["external_provider"],"free-exercise-db")
            import orchestration.tools.workout  # noqa: F401
            detail=FunctionRegistry.resolve_callable("workout.get_exercise_details")
            self.assertEqual(detail(str(exercise.id))["external_id"],"Pushups")

    def test_matching_uses_safe_semantic_aliases_and_rejects_unrelated_names(self):
        from workout.services import _match_catalog_exercise
        catalog=[{"id":"Dead_Bug","name":"Dead Bug"},{"id":"One_Handed_Hang","name":"One Handed Hang"},{"id":"Split_Squat_with_Dumbbells","name":"Split Squat with Dumbbells"},{"id":"Barbell_Side_Split_Squat","name":"Barbell Side Split Squat"}]
        self.assertIsNone(_match_catalog_exercise("Dead hang",catalog))
        self.assertIsNone(_match_catalog_exercise("Bulgarian split squat",catalog))
        self.assertIsNone(_match_catalog_exercise("Deadlift hangboard hybrid",catalog))

    def test_refresh_clears_a_legacy_wrong_match(self):
        exercise,_=resolve_exercise("Dead hang",defaults={"instructions":"Dead bug instructions","equipment":"body only"})
        exercise.external_provider="free-exercise-db"; exercise.external_id="Dead_Bug"
        exercise.enrichment_data={"source_name":"Dead Bug"}; exercise.demo_media_url="/media/wrong.gif"
        exercise.enriched_at=timezone.now(); exercise.save()
        client=self.Client(self.catalog,self.image)
        result=enrich_exercise(exercise.id,client=client,force=True)
        self.assertEqual(result["external_provider"],"")
        self.assertEqual(result["instructions"],"")
        self.assertEqual(result["demo_media_url"],"")
        self.assertTrue(result["enrichment_error"])

    def test_refresh_replaces_provider_fields_but_preserves_manual_overrides(self):
        from workout.services import update_exercise
        exercise,_=resolve_exercise("Push Up",defaults={"instructions":"stale wrong text","equipment":"wrong"})
        client=self.Client(self.catalog,self.image)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media,MEDIA_URL="/media/"):
            enriched=enrich_exercise(exercise.id,client=client,force=True)
            self.assertIn("Keep a straight body line",enriched["instructions"])
            self.assertEqual(enriched["equipment"],"body only")
            update_exercise(exercise.id,instructions="My verified cue")
            refreshed=enrich_exercise(exercise.id,client=client,force=True)
            self.assertEqual(refreshed["instructions"],"My verified cue")
            self.assertIn("instructions",refreshed["metadata"]["enrichment_overrides"])

    def test_push_up_uses_standard_not_plyometric_variant(self):
        from workout.services import _match_catalog_exercise
        catalog=[{"id":"Plyo","name":"Plyo Push-up"},{"id":"Standard","name":"Pushups"}]
        self.assertEqual(_match_catalog_exercise("Push-Up",catalog)["id"],"Standard")

    def test_enrichment_issue_action_exposes_missing_entries(self):
        import orchestration.tools.workout  # noqa: F401
        exercise,_=resolve_exercise("Uncatalogued movement")
        issues=FunctionRegistry.resolve_callable("workout.get_enrichment_issues")()
        self.assertEqual(issues["exercises"][0]["id"],str(exercise.id))

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


class GuidedWorkoutRevampTests(TestCase):
    def test_plan_ranges_are_preserved_and_become_set_targets(self):
        plan=save_plan(title="Ranges",sessions=[{"name":"Day","exercises":[{"name":"Split squat","sets":3,"reps_min":8,"reps_max":12,"per_side":True},{"name":"Dead hang","sets":2,"duration_seconds_min":30,"duration_seconds_max":60}]}])
        reps=plan["sessions"][0]["exercises"][0]; timed=plan["sessions"][0]["exercises"][1]
        self.assertEqual(reps["reps"],"8-12"); self.assertTrue(reps["metadata"]["per_side"])
        self.assertEqual(timed["phase_type"],"timed"); self.assertEqual(timed["duration_seconds"],60)
        session=start_session(plan=plan["id"],planned_session=plan["sessions"][0]["id"])
        self.assertEqual(session["exercises"][0]["set_logs"][0]["target"]["reps"],"8-12")
        self.assertEqual(session["exercises"][1]["set_logs"][0]["target"]["duration_seconds_min"],30)

    def test_named_session_cycles_and_detailed_sets(self):
        plan = save_plan(title="Intervals", sessions=[{"name":"Run day","guidance_mode":"guided","guidance_level":"full","exercises":[{"name":"Sprint","phase_type":"timed","sets":2,"duration_seconds":30,"rest_seconds":0,"block_name":"Fast loop","cycle_count":2,"set_targets":[{"duration_seconds":20},{"duration_seconds":30}]}]}])
        self.assertEqual(plan["sessions"][0]["name"], "Run day")
        session = start_session(plan=plan["id"], planned_session=plan["sessions"][0]["id"], mode="guided", guidance_level="full")
        self.assertEqual(session["planned_session_name"], "Run day")
        self.assertEqual(len(session["exercises"]), 2)
        self.assertEqual(len(session["exercises"][0]["set_logs"]), 2)
        self.assertEqual(session["exercises"][0]["set_logs"][0]["target"]["duration_seconds"], 20)

    def test_pause_draft_review_and_submit(self):
        from workout.services import set_session_status, update_set_log
        session = start_session(exercises=[{"name":"Squat","sets":1,"reps":5}])
        self.assertEqual(set_session_status(session["id"], "pause")["status"], "paused")
        self.assertEqual(set_session_status(session["id"], "resume")["status"], "active")
        set_id = session["exercises"][0]["set_logs"][0]["id"]
        changed = update_set_log(set_id, status="completed", actual={"reps":6,"weight_kg":80})
        self.assertTrue(changed["completed"])
        draft = finish_session(session["id"], draft=True)
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(set_session_status(session["id"], "submit")["status"], "completed")


class FullWorkoutActionSuiteTests(TestCase):
    def test_corv_can_crud_directory_plans_history_sets_and_goals(self):
        import orchestration.tools.workout  # noqa: F401
        create_exercise=FunctionRegistry.resolve_callable("workout.create_exercise")
        update_exercise_action=FunctionRegistry.resolve_callable("workout.update_exercise")
        update_plan_action=FunctionRegistry.resolve_callable("workout.update_plan")
        edit_session_action=FunctionRegistry.resolve_callable("workout.edit_session")
        edit_log_action=FunctionRegistry.resolve_callable("workout.edit_exercise_log")
        edit_set_action=FunctionRegistry.resolve_callable("workout.edit_set_log")
        list_goals_action=FunctionRegistry.resolve_callable("workout.list_goals")
        update_goal_action=FunctionRegistry.resolve_callable("workout.update_goal")
        delete_goal_action=FunctionRegistry.resolve_callable("workout.delete_goal")
        exercise=create_exercise("Action Squat",muscle_group="Legs")
        self.assertTrue(exercise["created"])
        self.assertEqual(update_exercise_action(exercise["id"],equipment="Rack")["equipment"],"Rack")
        plan=save_plan(title="Action program",sessions=[{"name":"Day A","exercises":[{"name":"Action Squat","sets":1,"reps":5}]}])
        changed_plan=update_plan_action(plan["id"],goal="Strength")
        self.assertEqual(changed_plan["goal"],"Strength")
        session=start_session(plan=plan["id"],planned_session=plan["sessions"][0]["id"])
        self.assertEqual(edit_session_action(session["id"],title="Corrected title")["title"],"Corrected title")
        log=session["exercises"][0]
        self.assertEqual(edit_log_action(log["id"],reps=6)["reps"],6)
        self.assertEqual(edit_set_action(log["set_logs"][0]["id"],actual={"reps":6})["set_logs"][0]["actual"]["reps"],6)
        goal=WorkoutGoal.objects.create(title="Old goal",metric="sessions_per_week",target_value=2)
        self.assertEqual(list_goals_action()["goals"][0]["id"],str(goal.id))
        self.assertEqual(update_goal_action(str(goal.id),title="New goal")["title"],"New goal")
        self.assertTrue(delete_goal_action(str(goal.id))["deleted"])

    def test_persisted_module_explains_full_safe_workflow(self):
        from orchestration.models import ToolModule
        instructions=ToolModule.objects.get(slug="workout").caller_instructions
        self.assertIn("full training lifecycle",instructions)
        self.assertIn("Supplying either replaces the complete programming",instructions)
        self.assertIn("never guess",instructions)


class WorkoutPlanExerciseOrderingTests(TestCase):
    def setUp(self):
        self.plan=WorkoutPlan.objects.create(title="Ordered plan")
        self.first=WorkoutPlanSession.objects.create(plan=self.plan,name="First",order_index=0)
        self.second=WorkoutPlanSession.objects.create(plan=self.plan,name="Second",order_index=1)
        self.squat,_=resolve_exercise("Ordering Squat")
        self.row,_=resolve_exercise("Ordering Row")

    def test_same_position_is_valid_in_different_named_sessions(self):
        WorkoutPlanExercise.objects.create(plan=self.plan,planned_session=self.first,exercise=self.squat,order_index=0)
        WorkoutPlanExercise.objects.create(plan=self.plan,planned_session=self.second,exercise=self.squat,order_index=0)
        self.assertEqual(WorkoutPlanExercise.objects.count(),2)

    def test_position_is_unique_inside_one_named_session(self):
        WorkoutPlanExercise.objects.create(plan=self.plan,planned_session=self.first,exercise=self.squat,order_index=0)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkoutPlanExercise.objects.create(plan=self.plan,planned_session=self.first,exercise=self.row,order_index=0)

    def test_legacy_plan_level_positions_remain_independent_and_unique(self):
        WorkoutPlanExercise.objects.create(plan=self.plan,exercise=self.squat,order_index=0)
        WorkoutPlanExercise.objects.create(plan=self.plan,planned_session=self.first,exercise=self.row,order_index=0)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkoutPlanExercise.objects.create(plan=self.plan,exercise=self.row,order_index=0)
