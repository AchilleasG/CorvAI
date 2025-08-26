from typing import List
from ninja import Router
from ninja.errors import HttpError
from django.db import transaction

from chat.models import Chat
from chat.schemas import ChatListItem, CreateChatIn, CreateChatOut, DeleteChatOut, RenameChatIn, RenameChatOut
from uuid import UUID
from chat.schemas import MessageOut

router = Router(tags=["chat"])

@router.get("/", response=List[ChatListItem])
def list_chats(request):
    qs = Chat.objects.only("id", "nickname").order_by("-id")
    return [{"chat_id": c.id, "chat_nickname": c.nickname or None} for c in qs]

@router.post("/", response=CreateChatOut)
@transaction.atomic
def create_chat(request, payload: CreateChatIn = None):
    nickname = (payload.chat_nickname if payload else "") or ""
    chat = Chat.objects.create(nickname=nickname)
    return {"chat_id": chat.id}

@router.delete("/{chat_id}", response=DeleteChatOut)
@transaction.atomic
def delete_chat(request, chat_id: UUID):
    try:
        chat = Chat.objects.get(id=chat_id)
    except Chat.DoesNotExist:
        raise HttpError(404, "Chat not found")
    chat.delete()
    return {"deleted": chat_id}

@router.get("/{chat_id}/messages", response=List[MessageOut])
def get_chat_messages(request, chat_id: UUID):
    try:
        chat = Chat.objects.get(id=chat_id)
    except Chat.DoesNotExist:
        raise HttpError(404, "Chat not found")

    messages = chat.messages.order_by("created_at")
    return [
        {
            "id": m.id,
            "role": m.role,
            "text": m.text,
            "created_at": m.created_at.isoformat() if m.created_at else None
        }
        for m in messages
    ]
@router.patch("/{chat_id}", response=RenameChatOut)
@transaction.atomic
def rename_chat(request, chat_id: UUID, payload: RenameChatIn):
    try:
        chat = Chat.objects.get(id=chat_id)
    except Chat.DoesNotExist:
        raise HttpError(404, "Chat not found")
    chat.nickname = payload.nickname or ""
    chat.save(update_fields=["nickname"])
    return {"chat_id": chat.id, "chat_nickname": chat.nickname}