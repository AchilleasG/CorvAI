from unittest.mock import patch

from django.test import TestCase

from chat.models import Chat, ChatMessage
from mcp.models import ModuleFunction, TaskPlan
from mcp.services import FunctionExecutionError, FunctionExecutor, TaskManagerAI, TaskManagerService


class FunctionExecutorTests(TestCase):
    def setUp(self):
        self.chat = Chat.objects.create()
        self.function = ModuleFunction.objects.get(module__slug="calendar", slug="add_event")

    def test_missing_parameter_triggers_error(self):
        with self.assertRaises(FunctionExecutionError) as ctx:
            FunctionExecutor.execute(
                chat=self.chat,
                function=self.function,
                parameters={"title": "Doctor", "time": "09:00"},
            )

        self.assertEqual(ctx.exception.code, "MISSING_PARAMETERS")


class TaskManagerServiceTests(TestCase):
    def setUp(self):
        self.chat = Chat.objects.create()
        ChatMessage.objects.create(chat=self.chat, role="user", text="Schedule my doctor appointment tomorrow", tags=["text-message"])

    @patch.object(TaskManagerAI, "generate_plan")
    def test_process_chat_requests_missing_info(self, mock_plan):
        mock_plan.return_value = {
            "status": "needs_info",
            "missing_information": [
                {"parameter": "event_time", "question": "What time should I set it for?"}
            ],
            "function_calls": [],
        }

        outcome = TaskManagerService.process_chat(self.chat)
        self.assertEqual(outcome.status, "awaiting_info")
        self.assertIn("event_time", outcome.frontman_context)
        plan = TaskPlan.objects.get(chat=self.chat)
        self.assertEqual(plan.status, "awaiting_info")

    @patch.object(TaskManagerAI, "generate_plan")
    def test_process_chat_executes_plan(self, mock_plan):
        mock_plan.return_value = {
            "status": "ready",
            "missing_information": [],
            "function_calls": [
                {
                    "module": "calendar",
                    "function": "add_event",
                    "parameters": {
                        "title": "Doctor",
                        "date": "2099-01-02",
                        "time": "09:00",
                    },
                }
            ],
        }

        outcome = TaskManagerService.process_chat(self.chat)
        self.assertEqual(outcome.status, "completed")
        self.assertIn("Doctor", outcome.frontman_context)
        plan = TaskPlan.objects.get(chat=self.chat)
        self.assertEqual(plan.status, "completed")

    @patch.object(TaskManagerAI, "generate_plan")
    def test_process_chat_executes_dummy_module_plan(self, mock_plan):
        mock_plan.return_value = {
            "status": "ready",
            "missing_information": [],
            "function_calls": [
                {
                    "module": "dummy_ops",
                    "function": "check_name",
                    "parameters": {"name": "Brianna"},
                }
            ],
        }

        outcome = TaskManagerService.process_chat(self.chat)
        self.assertEqual(outcome.status, "completed")
        self.assertIn("Brianna", outcome.frontman_context)
        plan = TaskPlan.objects.get(chat=self.chat)
        self.assertEqual(plan.status, "completed")

    def test_dummy_name_validator(self):
        function = ModuleFunction.objects.get(module__slug="dummy_ops", slug="check_name")

        with self.assertRaises(FunctionExecutionError):
            FunctionExecutor.execute(
                chat=self.chat,
                function=function,
                parameters={"name": "Ares"},
            )

        result = FunctionExecutor.execute(
            chat=self.chat,
            function=function,
            parameters={"name": "Brianna"},
        )
        self.assertEqual(result["accepted_name"], "Brianna")
