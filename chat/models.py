from django.db import models
import uuid

class Chat(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Chat {self.id} ({self.created_at})"


class ChatMessage(models.Model):
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
        ("tool", "Tool"),
    ]
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["chat", "created_at"]),
        ]

    def __str__(self):
        return f"{self.role}: {self.text[:50]}"
