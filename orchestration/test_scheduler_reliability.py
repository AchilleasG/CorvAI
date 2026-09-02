from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from orchestration.models import ScheduledTask,ScheduledTaskRun,UserMessage
from orchestration.scheduler import DUE_EXECUTION_NOTE,execute_task,poll_due_tasks
from orchestration.tools.scheduled_tasks import create_task

class SchedulerReliabilityTests(TestCase):
    def make_task(self,prompt="Send a reminder to grab your wallet"):
        return ScheduledTask.objects.create(prompt=prompt,recurrence="once",start_at=timezone.now(),next_run_at=timezone.now())

    @patch("orchestration.tools.messages.send_message_push_to_all")
    @patch("orchestration.tools.messages.ChatAIService.phrase_inbox_message",side_effect=lambda body,**kwargs:body)
    @patch("orchestration.scheduler.ChatAIService.summarize_scheduled_task",return_value="Reminder delivered")
    @patch("orchestration.scheduler._plan_with_no_clarifications")
    def test_due_reminder_creates_inbox_message(self,plan,_summary,_phrase,push):
        plan.side_effect=[
            {"done":False,"call":{"function_id":"messages.send_message","params":{"title":"Reminder","body":"Grab your wallet."}},"ask_user":None,"summary":"Sending now"},
            {"done":True,"call":None,"ask_user":None,"summary":"Delivered"},
        ]
        task=self.make_task(); run=execute_task(task)
        self.assertEqual(run.status,ScheduledTaskRun.STATUS_COMPLETED)
        self.assertEqual(UserMessage.objects.get().body,"Grab your wallet.")
        push.assert_called_once()
        request=plan.call_args_list[0].kwargs["user_request"]
        self.assertIn(DUE_EXECUTION_NOTE,request)
        self.assertIn("call messages.send_message now",request)

    @patch("orchestration.scheduler._plan_with_no_clarifications")
    def test_failed_tool_result_is_recorded_without_scheduler_crash(self,plan):
        plan.side_effect=[
            {"done":False,"call":{"function_id":"missing.tool","params":{}},"ask_user":None,"summary":""},
            {"done":True,"call":None,"ask_user":None,"summary":"Could not deliver"},
        ]
        task=self.make_task(); run=execute_task(task)
        self.assertEqual(run.status,ScheduledTaskRun.STATUS_FAILED)
        self.assertIn("not registered",run.error_summary)
        self.assertTrue(run.log_entries.filter(level="error").exists())

    @patch("orchestration.scheduler._plan_with_no_clarifications")
    def test_failed_one_shot_parent_is_not_marked_completed(self,plan):
        plan.side_effect=[
            {"done":False,"call":{"function_id":"missing.tool","params":{}},"ask_user":None,"summary":""},
            {"done":True,"call":None,"ask_user":None,"summary":"Failed"},
        ]
        task=self.make_task(); self.assertEqual(poll_due_tasks(),1); task.refresh_from_db()
        self.assertEqual(task.status,ScheduledTask.STATUS_FAILED)
        self.assertIsNone(task.next_run_at)
        self.assertFalse(task.is_running)

    def test_null_recurrence_defaults_to_once(self):
        payload=create_task("Test",recurrence=None)
        self.assertEqual(ScheduledTask.objects.get(id=payload["id"]).recurrence,ScheduledTask.RECURRENCE_ONCE)
