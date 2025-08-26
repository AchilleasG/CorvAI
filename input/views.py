from django.shortcuts import render
from ninja import Router
from chat.services import ChatService
from input.schemas import TextInputIn, TextInputOut
import uuid
from ninja import Router, File, Form
from ninja.files import UploadedFile
from django.http import JsonResponse
from django.core.files.storage import FileSystemStorage
from django.core.files.base import ContentFile
import os
import CorvAI.settings as settings
from openai_integration.services import ChatAIService
router = Router(tags=["Interaction"])

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
    file: UploadedFile = File(...)
):
    chat_uuid = uuid.UUID(chat_id)

    # Ensure voices dir exists
    voices_dir = os.path.join(settings.MEDIA_ROOT, "voices")
    os.makedirs(voices_dir, exist_ok=True)

    # Save file
    fs = FileSystemStorage(location=voices_dir)
    safe_name = f"{chat_uuid}_{file.name}"
    filename = fs.save(safe_name, ContentFile(file.read()))
    transcription = ChatAIService.transcribe_audio(os.path.join(voices_dir, filename))
    if transcription is None:
        return JsonResponse({"success": False, "message": "Failed to transcribe audio"}, status=500)
    response = ChatService.handle_user_input(chat_uuid, transcription)
    return JsonResponse(response, status=200)