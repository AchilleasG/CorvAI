from types import SimpleNamespace
from unittest.mock import Mock,patch
from django.test import TestCase
from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.models import ToolFunction,ToolModule
from orchestration.services import ModuleDirectory,PersonaService

class SemanticFirstGuidanceTests(TestCase):
    def test_action_schema_marks_tags_as_explicit_hard_filter(self):
        function=ToolFunction.objects.get(manifest_id="user_info.search_knowledge")
        self.assertIn("broad semantic search",function.description)
        self.assertIn("Hard tag filter",function.params_schema["properties"]["tags"]["description"])
        self.assertEqual(function.params_schema["properties"]["limit"]["default"],10)

    def test_module_and_persona_forbid_invented_filters(self):
        module=ToolModule.objects.get(slug="user_info")
        self.assertIn("Do not invent or infer tags",module.caller_instructions)
        with patch("orchestration.services.PersonaService.get_persona",return_value=None),patch("orchestration.services.UserInfoService.format_core_profile_block",return_value=""):
            prompt=PersonaService.build_persona_prompt()
        self.assertIn("do not invent tag, source, type",prompt)

    def test_planner_instructions_require_unfiltered_retry(self):
        response=SimpleNamespace(output_text='{"done":true,"call":null,"ask_user":null,"summary":"ok"}',usage=None)
        create=Mock(return_value=response);client=SimpleNamespace(responses=SimpleNamespace(create=create))
        with patch("orchestration.function_caller.get_client",return_value=client):
            FunctionCallOrchestrator._plan_next_action(user_request="How far am I from home?",tool_catalog=ModuleDirectory.function_catalog(),prior_results=[])
        text=create.call_args.kwargs["input"][0]["content"][0]["text"]
        self.assertIn("Do not add tags, source, entity type, user_id",text)
        self.assertIn("retry once without filters",text)
