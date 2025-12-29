from ninja import Schema
from typing import Literal,Optional
from uuid import UUID

class ChatListItem(Schema):
    chat_id: UUID
    chat_nickname: Optional[str] = None

class CreateChatIn(Schema):
    # Optional; create works with no body at all
    chat_nickname: Optional[str] = None

class CreateChatOut(Schema):
    chat_id: UUID

class DeleteChatOut(Schema):
    deleted: UUID


class RenameChatIn(Schema):
    nickname: Optional[str] = None

class RenameChatOut(Schema):
    chat_id: UUID
    chat_nickname: Optional[str] = None
class MessageOut(Schema):
    id: UUID
    role: Literal["user", "assistant", "system", "tool"]
    text: str
    created_at: Optional[str] = None
    message_type: Optional[Literal["user_visible", "tool_only", "system_note", "error"]] = None
    audience: Optional[Literal["user", "ai_stack"]] = None
    trace_id: Optional[str] = None
    call_id: Optional[str] = None
    job_id: Optional[UUID] = None
