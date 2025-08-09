from Corv.schemas import BaseSchema

# Pydantic schema for incoming payload
class TextInputIn(BaseSchema):
    text: str
    chat_id : int | None = None

# Pydantic schema for outgoing response
class TextInputOut(BaseSchema):
    success: bool
    message: str