from types import SimpleNamespace
from unittest.mock import Mock,patch
from django.test import TestCase
from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.models import ToolModule
from orchestration.registry import FunctionRegistry
from orchestration.services import PersonaService
import orchestration.tools.user_info

class AbsoluteNoteTimeGuidanceTests(TestCase):
    def test_module_forbids_all_relative_time_in_note_content(self):
        text=ToolModule.objects.get(slug="user_info").caller_instructions
        for phrase in ("today", "tomorrow", "yesterday", "now", "currently", "this morning", "next week", "in X days"):
            self.assertIn(phrase,text)
        self.assertIn("every temporal reference must be objective and absolute",text)
        self.assertIn("never invent a clock time",text)

    def test_action_content_schemas_repeat_absolute_time_requirement(self):
        add=FunctionRegistry.get("user_info.add_note").params_schema["properties"]["content"]["description"]
        update=FunctionRegistry.get("user_info.update_note").params_schema["properties"]["content"]["description"]
        self.assertIn("exact calendar dates/times",add)
        self.assertIn("Rewrite every temporal reference",update)

    def test_persona_receives_final_note_scan_rule(self):
        with patch("orchestration.services.PersonaService.get_persona",return_value=None),patch("orchestration.services.UserInfoService.format_core_profile_block",return_value=""):
            prompt=PersonaService.build_persona_prompt()
        self.assertIn("Every temporal reference stored in note content must be objective and absolute",prompt)
        self.assertIn("scan the proposed note",prompt)
        self.assertIn("never invent a clock time",prompt)

    def test_planner_prompt_explicitly_forbids_today(self):
        response=SimpleNamespace(output_text='{"done":true,"call":null,"ask_user":null,"summary":"ok"}',usage=None)
        create=Mock(return_value=response); client=SimpleNamespace(responses=SimpleNamespace(create=create))
        with patch("orchestration.function_caller.get_client",return_value=client),patch("orchestration.function_caller.PersonaService.build_persona_prompt",return_value="persona"):
            FunctionCallOrchestrator._plan_next_action(user_request="Note that the dose was given today",tool_catalog=[],prior_results=[])
        prompt=create.call_args.kwargs["input"][0]["content"][0]["text"]
        self.assertIn("EVERY temporal reference must be absolute",prompt)
        self.assertIn("replace today, tonight, tomorrow",prompt)
        self.assertIn("scan content and rewrite every relative temporal expression",prompt)
