from django.shortcuts import render
from ninja import Router
from input.schemas import TextInputIn, TextInputOut

router = Router(tags=["Interaction"])

@router.post("/text/", response=TextInputOut)
def receive_text(request, payload: TextInputIn):
    # Here’s where you’d hand off to Corv’s processing logic
    user_text = payload.text.strip()

    # Example: reject empty input
    if not user_text:
        return {"success": False, "message": "No text provided"}

    # Placeholder for your actual handling logic
    return {"success": True, "message": f"Received: {user_text}"}

