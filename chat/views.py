from typing import List, Optional
from ninja import Router
from ninja.errors import HttpError
from django.db import transaction
from django.db.models import Max
from django.db.models.functions import Coalesce

from chat.models import Chat
from chat.schemas import ChatListItem, CreateChatIn, CreateChatOut, DeleteChatOut, RenameChatIn, RenameChatOut
from uuid import UUID
from chat.schemas import MessageOut

router = Router(tags=["chat"])

@router.get("/", response=List[ChatListItem])
def list_chats(request, include_archived: bool = False):
    qs = Chat.objects.annotate(last_message_at=Max("messages__created_at")).annotate(
        last_activity_at=Coalesce("last_message_at", "created_at")
    )
    if not include_archived:
        qs = qs.filter(archived=False)
    qs = qs.only("id", "nickname", "created_at", "archived").order_by(
        "-last_activity_at", "-created_at"
    )
    return [
        {
            "chat_id": c.id,
            "chat_nickname": c.nickname or None,
            "last_activity_at": c.last_activity_at.isoformat()
            if getattr(c, "last_activity_at", None)
            else None,
            "archived": c.archived,
        }
        for c in qs
    ]

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
def get_chat_messages(request, chat_id: UUID, visible_only: bool = False, job_id: Optional[UUID] = None):
    try:
        chat = Chat.objects.get(id=chat_id)
    except Chat.DoesNotExist:
        raise HttpError(404, "Chat not found")

    messages = chat.messages.order_by("created_at")
    if job_id:
        messages = messages.filter(job_id=job_id)
    if visible_only:
        messages = messages.filter(message_type="user_visible", audience="user")
    return [
        {
            "id": m.id,
            "role": m.role,
            "text": m.text,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "message_type": m.message_type,
            "audience": m.audience,
            "trace_id": m.trace_id or None,
            "call_id": m.call_id or None,
            "job_id": m.job_id if getattr(m, "job_id", None) else None,
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
    updated_fields = []
    if payload.nickname is not None:
        chat.nickname = payload.nickname or ""
        updated_fields.append("nickname")
    if payload.archived is not None:
        chat.archived = payload.archived
        updated_fields.append("archived")
    if updated_fields:
        chat.save(update_fields=updated_fields)
    return {"chat_id": chat.id, "chat_nickname": chat.nickname, "archived": chat.archived}
