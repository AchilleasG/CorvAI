from unittest.mock import MagicMock, mock_open, patch

from django.test import SimpleTestCase

from openai_integration.services import ChatAIService


class AudioTranscriptionTests(SimpleTestCase):
    @patch("openai_integration.services.settings.transcription_model", "gpt-4o-mini-transcribe")
    @patch("openai_integration.services.get_client")
    @patch("builtins.open", new_callable=mock_open, read_data=b"audio")
    def test_transcription_uses_configured_default_model(self, _open, get_client):
        client = MagicMock()
        client.audio.transcriptions.create.return_value = MagicMock(text="Default model works.")
        get_client.return_value = client

        result = ChatAIService.transcribe_audio("/tmp/voice.webm", language="en")

        self.assertEqual(result, "Default model works.")
        self.assertEqual(
            client.audio.transcriptions.create.call_args.kwargs["model"],
            "gpt-4o-mini-transcribe",
        )

    @patch("openai_integration.services.get_client")
    @patch("builtins.open", new_callable=mock_open, read_data=b"audio")
    def test_transcription_pins_requested_language_without_translation(self, _open, get_client):
        client = MagicMock()
        client.audio.transcriptions.create.return_value = MagicMock(text="This stays English.")
        get_client.return_value = client

        result = ChatAIService.transcribe_audio(
            "/tmp/voice.webm",
            model="gpt-4o-mini-transcribe",
            language="en",
        )

        self.assertEqual(result, "This stays English.")
        kwargs = client.audio.transcriptions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-4o-mini-transcribe")
        self.assertEqual(kwargs["language"], "en")
        self.assertEqual(kwargs["response_format"], "json")
        self.assertIn("Do not translate", kwargs["prompt"])

    @patch("openai_integration.services.get_client")
    @patch("builtins.open", new_callable=mock_open, read_data=b"audio")
    def test_legacy_whisper_text_response_remains_supported(self, _open, get_client):
        client = MagicMock()
        client.audio.transcriptions.create.return_value = " Γεια σου "
        get_client.return_value = client

        result = ChatAIService.transcribe_audio(
            "/tmp/voice.webm",
            model="whisper-1",
            language="el",
        )

        self.assertEqual(result, "Γεια σου")
        self.assertEqual(
            client.audio.transcriptions.create.call_args.kwargs["response_format"],
            "text",
        )
