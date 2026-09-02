import json
from datetime import timedelta
from unittest.mock import patch
from django.test import RequestFactory, TestCase
from django.utils import timezone
from orchestration.models import UserNote
from orchestration.services import KnowledgeBaseService, UserInfoService
from orchestration.tasks import cleanup_expired_notes_task
from orchestration.tools.user_info import add_note as action_add_note, update_note as action_update_note
from orchestration.views import create_note, list_knowledge_tags, list_notes, update_note

class TimedNotesTests(TestCase):
    def setUp(self): self.factory=RequestFactory()
    def request(self,method,payload): return getattr(self.factory,method)("/api/orchestration/notes",data=json.dumps(payload),content_type="application/json")

    @patch("orchestration.services.UserInfoService._embed_text",return_value=None)
    def test_ui_create_and_update_expiry(self,_embed):
        expiry=(timezone.now()+timedelta(days=1)).replace(microsecond=0)
        created=create_note(self.request("post",{"content":"Temporary door code","expires_at":expiry.isoformat()}))
        self.assertEqual(created["expires_at"],expiry.isoformat())
        self.assertTrue(created["is_timed"])
        updated=update_note(self.request("patch",{"content":"Permanent door note","expires_at":None}),created["id"])
        self.assertIsNone(updated["expires_at"])
        self.assertFalse(updated["is_timed"])

    @patch("orchestration.services.UserInfoService._embed_text",return_value=[0.0]*1536)
    def test_expired_notes_are_never_listed_or_semantically_recalled(self,_embed):
        expired=UserInfoService.add_note(content="Old temporary secret",expires_at=timezone.now()-timedelta(seconds=1))
        live=UserInfoService.add_note(content="Live knowledge")
        listed=list_notes(self.factory.get("/api/orchestration/notes"))
        self.assertEqual([row["id"] for row in listed["notes"]],[str(live.id)])
        result=KnowledgeBaseService.search("temporary secret",limit=10)
        self.assertNotIn(str(expired.id),[row["id"] for row in result["results"]])

    @patch("orchestration.services.UserInfoService._embed_text",return_value=None)
    def test_expired_note_tags_do_not_leave_empty_filter_badges(self,_embed):
        UserInfoService.add_note(content="Expired",tags=["expired-only"],expires_at=timezone.now()-timedelta(seconds=1))
        UserInfoService.add_note(content="Live",tags=["live-tag"])
        payload=list_knowledge_tags(self.factory.get("/api/orchestration/knowledge/tags"))
        self.assertEqual(payload["tags"],["live-tag"])

    @patch("orchestration.services.UserInfoService._embed_text",return_value=None)
    def test_cleanup_soft_deletes_only_expired_notes(self,_embed):
        expired=UserInfoService.add_note(content="Expired",expires_at=timezone.now()-timedelta(minutes=1))
        future=UserInfoService.add_note(content="Future",expires_at=timezone.now()+timedelta(minutes=1))
        permanent=UserInfoService.add_note(content="Permanent")
        self.assertEqual(cleanup_expired_notes_task()["deleted"],1)
        self.assertIsNotNone(UserNote.objects.get(id=expired.id).deleted_at)
        self.assertIsNone(UserNote.objects.get(id=future.id).deleted_at)
        self.assertIsNone(UserNote.objects.get(id=permanent.id).deleted_at)

    @patch("orchestration.services.UserInfoService._embed_text",return_value=None)
    def test_corv_actions_create_and_clear_timed_note(self,_embed):
        expiry=(timezone.now()+timedelta(hours=2)).replace(microsecond=0)
        created=action_add_note("Short lived fact",expires_at=expiry.isoformat())
        self.assertEqual(created["expires_at"],expiry.isoformat())
        updated=action_update_note(created["id"],"Keep this",expires_at=None)
        self.assertIsNone(updated["expires_at"])
