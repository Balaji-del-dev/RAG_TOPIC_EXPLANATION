"""
Database models (Django ORM, stored in PostgreSQL). This is the full transcript.

    Conversation  one chat thread, owned by one user
    Message       one user question or one assistant answer, numbered in order

LangGraph's checkpointer keeps a separate, compact copy of the conversation
(recent messages + running summary) as the AI's working memory. These tables
are the record the user sees and that audits read; they are never trimmed.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Conversation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"  # idle too long: history is readable, new messages are refused

    # Random UUIDs, not 1, 2, 3...: they cannot be guessed or counted by other users.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    # Copy of the running summary from LangGraph, so the UI and search can show it.
    summary = models.TextField(blank=True)
    message_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-last_activity_at"]
        indexes = [
            # "my conversations, newest first" is the most common query
            models.Index(fields=["owner", "-last_activity_at"], name="conversation_owner_recent"),
            # the expiry job looks for active conversations idle since a given time
            models.Index(fields=["status", "last_activity_at"], name="conversation_status_idle"),
        ]

    def __str__(self) -> str:
        return f"{self.title or 'Untitled'} ({self.id})"

    @property
    def thread_id(self) -> str:
        """The LangGraph checkpointer thread for this conversation. Never taken from the client."""
        return str(self.id)

    def expires_at(self):
        hours = settings.CONVERSATIONS["CONVERSATION_IDLE_HOURS"]
        return self.last_activity_at + timedelta(hours=hours)


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"  # user question saved, answer not ready yet
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"  # the answer step failed; the question is kept

    class Resolution(models.TextChoices):
        UNCHANGED = "unchanged", "Unchanged"  # not a follow-up, used as typed
        LLM = "llm", "Rewritten by the LLM"
        FALLBACK = "fallback", "Joined with the previous question (LLM unavailable)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sequence = models.PositiveIntegerField()  # 1, 2, 3 ... within the conversation
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMPLETE)
    token_count = models.PositiveIntegerField(default=0)

    # Filled in for user questions by the conversation memory (LangGraph).
    is_follow_up = models.BooleanField(default=False)
    standalone_question = models.TextField(blank=True)  # what retrieval should search for
    resolution = models.CharField(max_length=10, choices=Resolution.choices, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["conversation", "sequence"], name="unique_message_sequence"),
        ]

    def __str__(self) -> str:
        return f"#{self.sequence} {self.role}: {self.content[:40]}"
