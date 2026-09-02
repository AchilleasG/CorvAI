from types import SimpleNamespace
from unittest.mock import Mock,patch
from django.test import TestCase
from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.models import ToolModule
from orchestration.registry import FunctionRegistry
import orchestration.tools.user_info  # register action metadata
from orchestration.services import ModuleDirectory,PersonaService

class NoteCreationGuidanceTests(TestCase):
    def test_module_and_action_descriptions_require_search_and_stable_facts(self):
        module=ToolModule.objects.get(slug="user_info")
        self.assertIn("always run a broad semantic",module.caller_instructions)
        self.assertIn("reuse the existing tag vocabulary",module.caller_instructions)
        self.assertIn("birth date or birth year rather than current age",module.caller_instructions)
        self.assertIn("semantically searching relevant knowledge first",FunctionRegistry.get("user_info.add_note").description)

    def test_persona_always_receives_note_writing_policy(self):
        with patch("orchestration.services.PersonaService.get_persona",return_value=None),patch("orchestration.services.UserInfoService.format_core_profile_block",return_value=""):
            prompt=PersonaService.build_persona_prompt()
        self.assertIn("before creating or updating any note",prompt)
        self.assertIn("reuses the user's existing tag vocabulary",prompt)
        self.assertIn("birth date or birth year rather than a current age",prompt)
        self.assertIn("Every temporal reference stored in note content must be objective and absolute",prompt)

    def test_planner_requires_relevant_search_before_writing(self):
        response=SimpleNamespace(output_text='{"done":true,"call":null,"ask_user":null,"summary":"ok"}',usage=None)
        create=Mock(return_value=response); client=SimpleNamespace(responses=SimpleNamespace(create=create))
        with patch("orchestration.function_caller.get_client",return_value=client):
            FunctionCallOrchestrator._plan_next_action(user_request="Remember that Alex is 29",tool_catalog=ModuleDirectory.function_catalog(),prior_results=[])
        text=create.call_args.kwargs["input"][0]["content"][0]["text"]
        self.assertIn("Before any note create/update, first search_knowledge broadly",text)
        self.assertIn("Save birth date/year instead of current age",text)
        self.assertIn("reuse the existing tag vocabulary",text)
