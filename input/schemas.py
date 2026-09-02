from Corv.schemas import BaseSchema
from typing import Any, Dict, Optional
from pydantic import Field

# Pydantic schema for incoming payload
class TextInputIn(BaseSchema):
    text: str
    chat_id : Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    file_ids: list[str] = Field(default_factory=list)

# Pydantic schema for outgoing response
class TextInputOut(BaseSchema):
    success: bool
    message: Optional[str] = None
    chat_id : Optional[str] = None
