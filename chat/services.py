from chat.models import Chat, ChatMessage
from openai_integration.services import ChatAIService
class ChatService:
    @staticmethod
    def get_chat_by_id(chat_id: int):
        try:
            return Chat.objects.get(id=chat_id)
        except Chat.DoesNotExist:
            return None

    @staticmethod
    def get_or_create_chat(chat_id: int):
        chat = ChatService.get_chat_by_id(chat_id)
        if not chat:
            chat = Chat.objects.create()
        return chat
    @staticmethod
    def get_chat_messages(chat_id: int):
        return ChatMessage.objects.filter(chat_id=chat_id).order_by('created_at')

    @staticmethod
    def construct_chat_context(chat_id: int, limit: int = 20):
        # TODO add corv's personality here
        chat = ChatService.get_chat_by_id(chat_id)
        if not chat:
            return None

        # Grab most recent N (index uses chat+created_at), then reverse to oldest→newest
        recent_qs = ChatMessage.objects.filter(chat_id=chat_id).order_by("-created_at")[:limit]
        messages = list(reversed(recent_qs))

        return {
            "chat": chat,
            "messages": messages,
        }

    @staticmethod
    def add_message_to_chat(chat_id: int, text: str, role: str = "user"):
        chat = ChatService.get_chat_by_id(chat_id)
        if not chat:
            return None
        
        message = ChatMessage(chat=chat, text=text, role=role)
        message.save()
        return message

    @staticmethod
    def get_chat_next_message(chat_id: int):
        chat_context = ChatService.construct_chat_context(chat_id)
        print(f"Chat context for chat {chat_id}: {chat_context}")
        if not chat_context:
            return {"success": False, "message": "Chat not found"}
        response = ChatAIService.generate_reply_from_context(chat_context)
        print(f"Generated response: {response}")
        if not response:
            return {"success": False, "message": "Failed to generate response"}
        return response

    @staticmethod
    def handle_user_input(chat_id: int, user_text: str):
        print(f"Handling user input for chat {chat_id}: {user_text}")
        chat = ChatService.get_or_create_chat(chat_id)
        chat_id = chat.id
        print(f"Chat {chat_id} exists or created.")
        message = ChatService.add_message_to_chat(chat_id, user_text, role="user")
        print(f"Message saved: {message}")
        if message is None:
            return {"success": False, "message": "Failed to save message"}
        response = ChatService.get_chat_next_message(chat_id)
        print(f"Response from chat service: {response}")
        # Assuming response contains the assistant's reply
        ChatService.add_message_to_chat(chat_id, response, role="assistant")
        return {"success": True, "message": response, "chat_id": str(chat_id)}
