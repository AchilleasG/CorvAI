from types import SimpleNamespace
from unittest.mock import Mock,patch
from django.test import SimpleTestCase
from orchestration.function_caller import FunctionCallOrchestrator

class PlannerActionCreationTests(SimpleTestCase):
    def test_prompt_requires_exactly_one_wrapped_action(self):
        response=SimpleNamespace(output_text='{"done":true,"call":null,"ask_user":null,"summary":"ok"}',usage=None)
        create=Mock(return_value=response); client=SimpleNamespace(responses=SimpleNamespace(create=create))
        with patch("orchestration.function_caller.get_client",return_value=client),patch("orchestration.function_caller.PersonaService.build_persona_prompt",return_value="persona"):
            FunctionCallOrchestrator._plan_next_action(user_request="Remember this",tool_catalog=[],prior_results=[])
        prompt=create.call_args.kwargs["input"][0]["content"][0]["text"]
        self.assertIn("Return exactly ONE JSON object",prompt)
        self.assertIn("Never concatenate JSON objects",prompt)
        self.assertIn("put function_id/params at the top level",prompt)
        self.assertIn("first return ONLY the search call",prompt)
        self.assertIn("Never output all three decisions together",prompt)
        self.assertIn("Do not repeat a successful identical search",prompt)

    def test_legacy_top_level_call_is_normalized(self):
        decision=FunctionCallOrchestrator._safe_json_load('{"function_id":"user_info.search_knowledge","params":{"query":"dog antibiotics"}}')
        self.assertFalse(decision["done"])
        self.assertEqual(decision["call"],{"function_id":"user_info.search_knowledge","params":{"query":"dog antibiotics"}})

    def test_concatenated_legacy_output_executes_only_first_step(self):
        raw=(
            '{"function_id":"user_info.search_knowledge","params":{"query":"dog"}}'
            '{"function_id":"user_info.add_note","params":{"content":"dog note"}}'
            '{"done":true,"call":null,"summary":"done"}'
        )
        decision=FunctionCallOrchestrator._safe_json_load(raw)
        self.assertEqual(decision["call"]["function_id"],"user_info.search_knowledge")
        self.assertEqual(decision["call"]["params"],{"query":"dog"})
        self.assertFalse(decision["done"])
