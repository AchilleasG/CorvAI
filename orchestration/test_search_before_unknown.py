from types import SimpleNamespace
from unittest.mock import Mock,patch
from django.test import TestCase
from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.models import ToolModule
from orchestration.services import ModuleDirectory,PersonaService

class SearchBeforeUnknownTests(TestCase):
    def test_shared_persona_requires_retrieval_before_unknown(self):
        with patch("orchestration.services.PersonaService.get_persona",return_value=None),patch("orchestration.services.UserInfoService.format_core_profile_block",return_value=""):
            prompt=PersonaService.build_persona_prompt()
        self.assertIn("Search-before-unknown rule",prompt)
        self.assertIn("user_info.search_knowledge first",prompt)
        self.assertIn("internet_search.search",prompt)

    def test_both_module_hints_persist_search_before_unknown(self):
        personal=ToolModule.objects.get(slug="user_info").caller_instructions
        general=ToolModule.objects.get(slug="internet_search").caller_instructions
        self.assertIn("Search-before-unknown rule",personal)
        self.assertIn("Search-before-unknown rule",general)

    def test_function_caller_cannot_finish_unknown_before_search(self):
        response=SimpleNamespace(output_text='{"done":true,"call":null,"ask_user":null,"summary":"ok"}',usage=None)
        create=Mock(return_value=response);client=SimpleNamespace(responses=SimpleNamespace(create=create))
        with patch("orchestration.function_caller.get_client",return_value=client):
            FunctionCallOrchestrator._plan_next_action(user_request="Do you know where I stayed?",tool_catalog=ModuleDirectory.function_catalog(),prior_results=[])
        instructions=create.call_args.kwargs["input"][0]["content"][0]["text"]
        self.assertIn("never finish with a summary saying or implying that you do not know",instructions)
        self.assertIn("search personal knowledge first",instructions)
