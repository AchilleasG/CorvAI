import tempfile
import uuid
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.test import SimpleTestCase

from input.views import _audio_extension, input_voice


class AudioFormatDetectionTests(SimpleTestCase):
    def test_detects_browser_audio_containers(self):
        samples = {
            b"\x1a\x45\xdf\xa3" + b"\0" * 12: ".webm",
            b"\0\0\0\x18ftypM4A " + b"\0" * 4: ".m4a",
            b"OggS" + b"\0" * 12: ".ogg",
            b"RIFF\0\0\0\0WAVE" + b"\0" * 4: ".wav",
            b"ID3" + b"\0" * 13: ".mp3",
            b"\xff\xfb" + b"\0" * 14: ".mp3",
        }

        for audio_bytes, extension in samples.items():
            with self.subTest(extension=extension):
                self.assertEqual(_audio_extension(audio_bytes), extension)

    def test_rejects_unknown_bytes(self):
        self.assertEqual(_audio_extension(b"not an audio container"), "")


class BlankTranscriptionTests(SimpleTestCase):
    @patch("input.views.ChatService.handle_user_input")
    @patch("input.views.ChatAIService.transcribe_audio", return_value="   ")
    def test_blank_transcription_never_reaches_chat(self, _transcribe, handle_user_input):
        audio = SimpleUploadedFile(
            "voice.webm",
            b"\x1a\x45\xdf\xa3" + b"\0" * 1024,
            content_type="audio/webm",
        )
        request = RequestFactory().post("/api/input/voice/")

        with tempfile.TemporaryDirectory() as media_root:
            with patch("input.views.settings.MEDIA_ROOT", media_root):
                response = input_voice(
                    request,
                    chat_id=str(uuid.uuid4()),
                    language="",
                    file=audio,
                )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"No speech", response.content)
        handle_user_input.assert_not_called()
