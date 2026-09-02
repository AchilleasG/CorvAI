from unittest.mock import patch

from django.test import TestCase

from chat.models import Chat, ChatMessage
from chat.services import ChatService


class TokenBudgetedChatContextTests(TestCase):
    def setUp(self):
        self.chat = Chat.objects.create()

    def add(self, text, role="user", **kwargs):
        return ChatMessage.objects.create(chat=self.chat, text=text, role=role, **kwargs)

    def test_short_history_is_not_limited_to_forty_turns(self):
        for index in range(70):
            self.add(f"short message {index}", "user" if index % 2 == 0 else "assistant")

        context = ChatService.construct_chat_context(self.chat.id, token_budget=10000)

        self.assertEqual(len(context["messages"]), 70)
        self.assertEqual(context["messages"][0].text, "short message 0")
        self.assertEqual(context["messages"][-1].text, "short message 69")

    @patch("chat.services.ChatAIService.summarize_chat_history", return_value="Durable summary")
    def test_overflow_keeps_recent_messages_and_persists_summary(self, summarize):
        stored = [self.add((f"message {index} " + "x" * 120), "user" if index % 2 == 0 else "assistant") for index in range(12)]

        first = ChatService.construct_chat_context(self.chat.id, token_budget=260)

        self.assertEqual(first["messages"][0].text, "Durable summary")
        self.assertEqual(str(first["messages"][-1].id), str(stored[-1].id))
        self.assertGreater(first["context_meta"]["summarized_messages"], 0)
        summary = ChatMessage.objects.get(metadata__rolling_context_summary=True)
        self.assertEqual(summary.audience, "ai_stack")
        self.assertEqual(summary.message_type, "system_note")
        summarize.assert_called_once()

        ChatService.construct_chat_context(self.chat.id, token_budget=260)
        # Adding the summary itself may rotate one additional message. That message is
        # summarized once, then the window stabilizes without duplicate work.
        self.assertEqual(summarize.call_count, 2)
        self.assertEqual(len(summarize.call_args_list[1].args[1]), 1)
        ChatService.construct_chat_context(self.chat.id, token_budget=260)
        self.assertEqual(summarize.call_count, 2)

    def test_only_opted_in_tool_results_enter_context(self):
        self.add("question")
        self.add("private tool payload", "tool", message_type="tool_only", audience="ai_stack")
        included = self.add(
            "action result summary", "tool", message_type="tool_only", audience="ai_stack",
            metadata={"include_in_context": True},
        )

        context = ChatService.construct_chat_context(self.chat.id, token_budget=1000)

        self.assertIn(str(included.id), [str(message.id) for message in context["messages"]])
        self.assertNotIn("private tool payload", [message.text for message in context["messages"]])


class DynamicChatTitleTests(TestCase):
    @patch("chat.services.ChatService.get_chat_next_message", return_value="Hello")
    @patch("chat.services.ChatAIService.generate_chat_title", return_value='Title: Plan a Japan Holiday!')
    def test_first_message_generates_and_saves_title(self, generate_title, _reply):
        chat = Chat.objects.create()
        ChatService.handle_user_input(chat.id, "Help me plan a holiday to Japan")
        chat.refresh_from_db()
        self.assertEqual(chat.nickname, "Plan a Japan Holiday")
        generate_title.assert_called_once_with("Help me plan a holiday to Japan")

    @patch("chat.services.ChatService.get_chat_next_message", return_value="Hello")
    @patch("chat.services.ChatAIService.generate_chat_title")
    def test_existing_title_is_preserved(self, generate_title, _reply):
        chat = Chat.objects.create(nickname="My custom name")
        ChatService.handle_user_input(chat.id, "A new message")
        chat.refresh_from_db()
        self.assertEqual(chat.nickname, "My custom name")
        generate_title.assert_not_called()

    @patch("chat.services.ChatService.get_chat_next_message", return_value="Still works")
    @patch("chat.services.ChatAIService.generate_chat_title", side_effect=RuntimeError("offline"))
    def test_title_failure_does_not_block_chat(self, _generate_title, _reply):
        chat = Chat.objects.create()
        result = ChatService.handle_user_input(chat.id, "Can you help me?")
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Still works")


class ProviderErrorReplyTests(TestCase):
    class ProviderError(Exception):
        def __init__(self, message, *, status_code=None, body=None):
            super().__init__(message)
            self.status_code = status_code
            self.body = body

    def test_exhausted_credits_have_an_actionable_reply(self):
        exc = self.ProviderError(
            "Request failed",
            status_code=429,
            body={
                "error": {
                    "type": "insufficient_quota",
                    "code": "credit_balance_exhausted",
                    "message": "You have no credits remaining.",
                }
            },
        )

        reply = ChatService._safe_assistant_reply(exc)

        self.assertEqual(reply, ChatService._PROVIDER_QUOTA_REPLY)
        self.assertIn("no API credits remaining", reply)

    def test_generic_429_is_described_as_temporary_rate_limiting(self):
        exc = self.ProviderError("Too Many Requests", status_code=429)

        self.assertEqual(
            ChatService._safe_assistant_reply(exc),
            ChatService._PROVIDER_RATE_LIMIT_REPLY,
        )

    def test_authentication_failure_points_to_provider_settings(self):
        exc = self.ProviderError("Unauthorized", status_code=401)

        self.assertEqual(
            ChatService._safe_assistant_reply(exc),
            ChatService._PROVIDER_AUTH_REPLY,
        )

    @patch(
        "chat.services.ChatAIService.frontman_decision",
        side_effect=ProviderError(
            "Request failed: insufficient_quota",
            status_code=429,
        ),
    )
    def test_frontman_quota_failure_returns_clear_reply(self, _frontman):
        chat = Chat.objects.create()
        ChatMessage.objects.create(chat=chat, role="user", text="Hello")

        reply = ChatService.get_chat_next_message(chat.id)

        self.assertEqual(reply, ChatService._PROVIDER_QUOTA_REPLY)
