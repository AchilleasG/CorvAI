from __future__ import annotations

import uuid
from django.db import models

class Chat(models.Model):
    id = models.TextField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    nickname = models.TextField(max_length=255, blank=True, null=True)
    archived = models.BooleanField(default=False, db_index=True)

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
    MESSAGE_TYPE_CHOICES = [
        ("user_visible", "User Visible"),
        ("tool_only", "Tool Only"),
        ("system_note", "System Note"),
        ("error", "Error"),
    ]
    AUDIENCE_CHOICES = [
        ("user", "User"),
        ("ai_stack", "AI Stack"),
    ]

    id = models.TextField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    message_type = models.CharField(
        max_length=20, choices=MESSAGE_TYPE_CHOICES, default="user_visible"
    )
    audience = models.CharField(
        max_length=20, choices=AUDIENCE_CHOICES, default="user"
    )
    trace_id = models.CharField(max_length=255, blank=True, default="")
    call_id = models.CharField(max_length=255, blank=True, default="")
    # Optional foreign key; string reference avoids circular import at load time.
    job = models.ForeignKey(
        "orchestration.Job",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="messages",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["chat", "created_at"]),
        ]

    def __str__(self):
        return f"{self.role}: {self.text[:50]}"
