from __future__ import annotations

import json
import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from orchestration.crypto import decrypt_value, encrypt_value


class SshMachine(models.Model):
    AUTH_PASSWORD = "password"
    AUTH_PRIVATE_KEY = "private_key"
    AUTH_AGENT = "agent"
    AUTH_CHOICES = [
        (AUTH_PASSWORD, "Password"),
        (AUTH_PRIVATE_KEY, "Private key"),
        (AUTH_AGENT, "SSH agent"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(
        default=22,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    username = models.CharField(max_length=255)
    auth_type = models.CharField(max_length=24, choices=AUTH_CHOICES, default=AUTH_PRIVATE_KEY)
    credential_encrypted = models.TextField(blank=True, default="")
    host_key_fingerprint = models.CharField(max_length=128, blank=True, default="")
    allow_ai_commands = models.BooleanField(default=False)
    connect_timeout_seconds = models.PositiveIntegerField(default=15)
    command_timeout_seconds = models.PositiveIntegerField(default=120)
    keepalive_seconds = models.PositiveIntegerField(default=30)
    notes = models.TextField(blank=True, default="")
    last_connected_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name"]), models.Index(fields=["host", "port"])]

    def __str__(self):
        return f"{self.name} ({self.username}@{self.host}:{self.port})"

    @property
    def has_credentials(self) -> bool:
        return self.auth_type == self.AUTH_AGENT or bool(self.credential_encrypted)

    def set_credentials(self, *, password: str = "", private_key: str = "", passphrase: str = ""):
        payload = {
            "password": password if self.auth_type == self.AUTH_PASSWORD else "",
            "private_key": private_key if self.auth_type == self.AUTH_PRIVATE_KEY else "",
            "passphrase": passphrase if self.auth_type == self.AUTH_PRIVATE_KEY else "",
        }
        if not any(payload.values()):
            self.credential_encrypted = ""
            return
        self.credential_encrypted = encrypt_value(json.dumps(payload))

    def get_credentials(self) -> dict:
        if not self.credential_encrypted:
            return {}
        return json.loads(decrypt_value(self.credential_encrypted))


class SshCommandRecord(models.Model):
    SOURCE_API = "api"
    SOURCE_ASSISTANT = "assistant"
    SOURCE_CHOICES = [(SOURCE_API, "API"), (SOURCE_ASSISTANT, "Assistant")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    machine = models.ForeignKey(SshMachine, on_delete=models.CASCADE, related_name="command_records")
    command = models.TextField()
    source = models.CharField(max_length=24, choices=SOURCE_CHOICES, default=SOURCE_API)
    exit_status = models.IntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    succeeded = models.BooleanField(default=False)
    error_summary = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["machine", "created_at"])]

    def __str__(self):
        return f"{self.machine.name}: {self.command[:60]}"
