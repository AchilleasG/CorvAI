import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from ninja.errors import HttpError

from orchestration.models import UserNote
from orchestration.views import create_note, delete_note, list_notes, update_note


class NotesApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, method: str, payload: dict | None = None):
        return getattr(self.factory, method)(
            "/api/orchestration/notes",
            data=json.dumps(payload or {}),
            content_type="application/json",
        )

    @patch("orchestration.services.UserInfoService._embed_text", return_value=None)
    def test_create_list_text_and_tag_filters(self, _embed):
        first = create_note(self.request("post", {"content": "Prefers quiet morning flights", "source": "spoofed", "tags": ["travel", "preferences"]}))
        create_note(self.request("post", {"content": "Project deploy checklist", "tags": ["work"]}))

        by_text = list_notes(self.factory.get("/api/orchestration/notes"), query="morning")
        by_tags = list_notes(self.factory.get("/api/orchestration/notes"), tags="travel,preferences")

        self.assertEqual(by_text["count"], 1)
        self.assertEqual(by_text["notes"][0]["id"], first["id"])
        self.assertEqual(by_tags["count"], 1)
        self.assertEqual(by_tags["notes"][0]["id"], first["id"])
        self.assertEqual(by_tags["tags"], ["preferences", "travel", "work"])
        self.assertEqual(first["source"], "notes_ui")

    @patch("orchestration.services.UserInfoService._embed_text", return_value=None)
    def test_update_and_soft_delete(self, _embed):
        created = create_note(self.request("post", {"content": "Old text", "tags": ["old"]}))
        note_id = created["id"]

        updated = update_note(self.request("patch", {"content": "New text", "source": "spoofed", "tags": ["new"]}), note_id)
        deleted = delete_note(self.request("delete"), note_id)

        self.assertEqual(updated["content"], "New text")
        self.assertEqual(updated["tags"], ["new"])
        self.assertEqual(updated["source"], "notes_ui")
        self.assertTrue(deleted["deleted"])
        self.assertIsNotNone(UserNote.objects.get(id=note_id).deleted_at)
        self.assertEqual(list_notes(self.factory.get("/api/orchestration/notes"))["count"], 0)

    def test_empty_note_is_rejected(self):
        with self.assertRaises(HttpError) as error:
            create_note(self.request("post", {"content": "   "}))
        self.assertEqual(error.exception.status_code, 400)
