import os
import re
import uuid

import CorvAI.settings as settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.http import JsonResponse
from ninja import File, Form, Router
from ninja.files import UploadedFile
from openai import BadRequestError

from chat.services import ChatService
from input.schemas import TextInputIn, TextInputOut
from openai_integration.services import ChatAIService

router = Router(tags=["Interaction"])


def _audio_extension(data: bytes) -> str:
    """Infer a supported audio container from its magic bytes."""
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return ".m4a"
    if data.startswith(b"OggS"):
        return ".ogg"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return ".wav"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return ".mp3"
    return ""

@router.post("/text/", response=TextInputOut)
def receive_text(request, payload: TextInputIn):
    # Get chat context from chat id
    

    # Extract the text from the payload
    user_text = payload.text
    

    # Example: reject empty input
    if not user_text:
        return {"success": False, "message": "No text provided"}
    response = ChatService.handle_user_input(payload.chat_id, user_text)
    return response




@router.post("/voice/")
def input_voice(
    request,
    chat_id: str = Form(...),
    language: str = Form(""),
    file: UploadedFile = File(...)
):
    chat_uuid = uuid.UUID(chat_id)

    # Ensure voices dir exists
    voices_dir = os.path.join(settings.MEDIA_ROOT, "voices")
    os.makedirs(voices_dir, exist_ok=True)

    audio_bytes = file.read()
    if len(audio_bytes) < 512:
        return JsonResponse({"success": False, "message": "The voice recording was empty or too short"}, status=400)
    detected_extension = _audio_extension(audio_bytes)
    if not detected_extension:
        return JsonResponse(
            {"success": False, "message": "The browser produced an unsupported audio format. Please try recording again."},
            status=400,
        )

    # Save using the detected container, rather than trusting a browser-supplied extension.
    fs = FileSystemStorage(location=voices_dir)
    safe_name = f"{chat_uuid}_voice{detected_extension}"
    filename = fs.save(safe_name, ContentFile(audio_bytes))
    normalized_language = (language or "").strip().lower()
    if normalized_language and not re.fullmatch(r"[a-z]{2}", normalized_language):
        fs.delete(filename)
        return JsonResponse({"success": False, "message": "Voice language must be a two-letter ISO code"}, status=400)
    try:
        try:
            transcription = ChatAIService.transcribe_audio(
                os.path.join(voices_dir, filename),
                language=normalized_language or None,
            )
        except BadRequestError:
            return JsonResponse(
                {
                    "success": False,
                    "message": "The audio service could not read this recording. Please record it again.",
                },
                status=400,
            )
    finally:
        fs.delete(filename)
    transcription = (transcription or "").strip()
    if not transcription:
        return JsonResponse(
            {"success": False, "message": "No speech was detected in the recording"},
            status=400,
        )
    response = ChatService.handle_user_input(chat_uuid, transcription)
    return JsonResponse(response, status=200)
