from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from chat.models import Chat, ChatMessage
from chat.services import ChatService
from openai_integration.personality import (
    build_personality_system_message,
    build_user_profile_message,
)
from openai_integration.services import ChatAIService


class ChatContextTests(TestCase):
    def test_construct_chat_context_normalizes_dynamic_context(self):
        chat = Chat.objects.create()

        context = ChatService.construct_chat_context(
            chat.id,
            dynamic_context=[
                "Runtime hint",
                {"role": "user", "text": "Shadow question"},
                "",
            ],
        )

        normalized = context["dynamic_context"]
        self.assertEqual(len(normalized), 3)
        self.assertIn("Capabilities overview", normalized[0]["text"])
        first_context = normalized[0]["text"]
        self.assertIn("Dummy Ops", first_context)
        self.assertIn("Execution protocol", first_context)
        self.assertIn("action-prompt", first_context)
        self.assertEqual(normalized[1]["role"], "system")
        self.assertEqual(normalized[1]["text"], "Runtime hint")
        self.assertEqual(normalized[2]["role"], "user")
        self.assertEqual(normalized[2]["text"], "Shadow question")
        self.assertIsNone(context["user_profile_id"])

    def test_generate_reply_prefers_personality_and_dynamic_context(self):
        chat = Chat.objects.create()
        ChatMessage.objects.create(chat=chat, role="user", text="Hey Corv?")
        context = ChatService.construct_chat_context(chat.id, dynamic_context="Runtime update")

        with patch.object(
            ChatAIService, "_messages_to_openai_input", wraps=ChatAIService._messages_to_openai_input
        ) as mock_to_input, patch.object(
            ChatAIService.client.responses, "create", return_value=SimpleNamespace(output_text="ok")
        ) as mock_create:
            reply = ChatAIService.generate_reply_from_context(context)

        self.assertEqual(reply, "ok")
        mock_create.assert_called_once()
        combined_arg = mock_to_input.call_args[0][0]
        self.assertEqual(combined_arg[0]["role"], "system")
        self.assertIn("Corv", combined_arg[0]["text"])
        self.assertIn("Rae Morales", combined_arg[1]["text"])
        capability_context = combined_arg[2]["text"]
        self.assertIn("Capabilities overview", capability_context)
        self.assertIn("Dummy Ops", capability_context)
        self.assertIn("action-prompt", capability_context)
        self.assertEqual(combined_arg[3]["text"], "Runtime update")
        self.assertTrue(isinstance(combined_arg[4], ChatMessage))

    def test_personality_message_matches_json_payload(self):
        """Sanity check to make sure the JSON prompt is wired through."""
        prompt = build_personality_system_message()
        self.assertIn("operations co-pilot", prompt)

    def test_user_profile_message_includes_preferences(self):
        msg = build_user_profile_message()
        self.assertIn("Rae Morales", msg)
        self.assertIn("Goals", msg)
