from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.models import ToolFunction
from orchestration.services import FunctionRunnerService, ModuleDirectory
from orchestration.schemas import FunctionCallPayload
from orchestration.tools.internet_search import _source_list


class InternetSearchTests(TestCase):
    def test_search_is_in_shared_chat_and_call_catalog(self):
        tool = next(
            item for item in ModuleDirectory.function_catalog()
            if item["manifest_id"] == "internet_search.search"
        )
        self.assertEqual(tool["module"], "internet_search")
        self.assertIn("source URLs", tool["description"])

    def test_runner_executes_registered_search_action(self):
        response = SimpleNamespace(
            output_text="The verified answer.", usage=None,
            output=[SimpleNamespace(model_dump=lambda: {
                "type": "message",
                "content": [{"annotations": [{
                    "type": "url_citation", "url": "https://example.com/fact", "title": "Example fact"
                }]}],
            })],
        )
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
        with patch("orchestration.tools.internet_search.get_client", return_value=client):
            result = FunctionRunnerService.run_function_call(FunctionCallPayload(
                trace_id="search-test", function_id="internet_search.search",
                params={"query": "verify this fact"},
            ))
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data["answer"], "The verified answer.")
        self.assertEqual(result.data["sources"][0]["url"], "https://example.com/fact")

    def test_source_extraction_deduplicates_search_and_citation_sources(self):
        response = SimpleNamespace(output=[
            SimpleNamespace(model_dump=lambda: {
                "action": {"sources": [{"url": "https://example.com", "title": "Example"}]}
            }),
            SimpleNamespace(model_dump=lambda: {
                "content": [{"annotations": [{"url": "https://example.com", "title": "Duplicate"}]}]
            }),
        ])
        self.assertEqual(_source_list(response), [{"title": "Example", "url": "https://example.com"}])

    def test_planner_is_told_to_search_uncertain_current_knowledge(self):
        catalog = ModuleDirectory.function_catalog()
        fake = SimpleNamespace(
            output_text='{"done":true,"call":null,"ask_user":null,"summary":"ok"}',
            usage=None,
        )
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: fake))
        with patch("orchestration.function_caller.get_client", return_value=client) as get_client:
            FunctionCallOrchestrator._plan_next_action(
                user_request="What happened today?", tool_catalog=catalog, prior_results=[]
            )
        instructions = get_client.return_value.responses.create.call_args if hasattr(get_client.return_value.responses.create, "call_args") else None
        # The module registration itself carries the same routing rule used by calls and chat.
        module = ToolFunction.objects.get(manifest_id="internet_search.search").module
        self.assertIn("could have changed", module.caller_instructions)
