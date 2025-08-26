from Corv.schemas import BaseSchema
from typing import Optional

# Pydantic schema for incoming payload
class TextInputIn(BaseSchema):
    text: str
    chat_id : Optional[str] = None

# Pydantic schema for outgoing response
class TextInputOut(BaseSchema):
    success: bool
    message: Optional[str] = None
    chat_id : Optional[str] = None