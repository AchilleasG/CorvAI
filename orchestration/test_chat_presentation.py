from unittest.mock import patch
from django.test import TestCase
from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.models import Job,ToolModule
from orchestration.schemas import FunctionResultPayload
from orchestration.services import JobService,PersonaService
from chat.models import Chat
from chat.services import ChatService

class ChatPresentationTests(TestCase):
    def test_channel_specific_presentation_rules(self):
        text=FunctionCallOrchestrator._presentation_instructions(chat_id="chat")
        call=FunctionCallOrchestrator._presentation_instructions(call_session_id="call")
        self.assertIn("polished, concise GitHub-flavored Markdown",text)
        self.assertIn("[descriptive source](https://...)",text)
        self.assertIn("Never emit or speak Markdown syntax",call)
        self.assertNotIn("GitHub-flavored Markdown",call)

    def test_sources_survive_large_result_compression(self):
        result=FunctionResultPayload(trace_id="t",call_id="c",status="ok",data={"answer":"x"*7000,"sources":[{"title":"Example story","url":"https://news.example.com/story"}]})
        compact={"summary":"news","key_facts":[],"important_ids":[],"warnings":[],"used_ai_summary":True}
        with patch.object(FunctionCallOrchestrator,"_compact_result_context",return_value=compact):
            payload=FunctionCallOrchestrator._coerce_result_payload(result,function_id="internet_search.search",params={"query":"news"})
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["sources"],[{"title":"Example story","url":"https://news.example.com/story","site_name":"news.example.com"}])
        self.assertEqual(payload["data"]["summary"],"news")

    def test_sources_attach_once_to_final_chat_message(self):
        chat=Chat.objects.create()
        job=JobService.create_job(chat=chat,user_visible_summary="Research")
        sources=[{"title":"Example","url":"https://example.com/story","site_name":"example.com"}]
        FunctionCallOrchestrator._remember_job_sources(job,sources)
        message=ChatService.add_message_to_chat(chat.id,"## Result",role="assistant",job=job)
        self.assertEqual(message.metadata["sources"],sources)
        job.refresh_from_db()
        self.assertNotIn("pending_sources",job.metadata)

    def test_persona_distinguishes_text_from_calls(self):
        with patch("orchestration.services.PersonaService.get_persona",return_value=None),patch("orchestration.services.UserInfoService.format_core_profile_block",return_value=""):
            prompt=PersonaService.build_persona_prompt()
        self.assertIn("in text chat, use polished GitHub-flavored Markdown",prompt)
        self.assertIn("In calls or other spoken output, never speak Markdown syntax",prompt)
