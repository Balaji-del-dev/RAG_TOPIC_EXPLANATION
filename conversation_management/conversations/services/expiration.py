"""
10. SESSION EXPIRATION HANDLING                    (Redis TTL + Django ORM)
==============================================================================

The problem
    Sessions and conversations cannot live forever. Old sessions are a security
    risk on shared computers, and old AI memory wastes storage and can mix
    yesterday's context into today's questions.

What it does
    Two clocks, for two different things:

    Chat session    idle 30 min (CHAT_SESSION_IDLE_SECONDS), stored in Redis
                    -> Redis deletes it by itself (TTL). The next message starts
                       a new session and, without a conversation ID, a new
                       conversation.
    Conversation    idle 24 h (CONVERSATION_IDLE_HOURS), stored in PostgreSQL
                    -> it becomes read-only: history stays visible, new
                       messages get 410 Gone ("start a new conversation"), and
                       its LangGraph memory is deleted.

How it works
    1. Sessions: nothing to do. The TTL is set on every save (user_sessions.py),
       and Redis removes expired keys.
    2. Conversations, lazily: ensure_writable() runs before every new message.
       If last_activity_at is older than the limit, the conversation is marked
       expired right then, and the request gets 410.
    3. Conversations, in bulk: the command `python manage.py expire_conversations`
       (run from cron every few minutes) expires every idle conversation and
       deletes its checkpointer thread, freeing PostgreSQL storage.
    4. Reading an expired conversation still works. Only writing is refused.

Why two clocks?
    A session is "this visit". A conversation is "this topic", which the user
    may come back to later the same day.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from conversations.exceptions import ConversationExpired
from conversations.models import Conversation

logger = logging.getLogger("conversations")


def idle_cutoff(now=None):
    hours = settings.CONVERSATIONS["CONVERSATION_IDLE_HOURS"]
    return (now or timezone.now()) - timedelta(hours=hours)


def is_idle_expired(conversation: Conversation, now=None) -> bool:
    return conversation.last_activity_at < idle_cutoff(now)


def mark_expired(conversation: Conversation) -> None:
    from conversations.services.memory import delete_memory

    updated = Conversation.objects.filter(pk=conversation.pk, status=Conversation.Status.ACTIVE).update(
        status=Conversation.Status.EXPIRED
    )
    conversation.status = Conversation.Status.EXPIRED
    if updated:
        delete_memory(conversation.thread_id)
        logger.info("conversation expired conversation=%s", conversation.pk)


def ensure_writable(conversation: Conversation) -> None:
    """Raise 410 if the conversation is expired (or has just become expired)."""
    if conversation.status == Conversation.Status.EXPIRED:
        raise ConversationExpired()
    if is_idle_expired(conversation):
        mark_expired(conversation)
        raise ConversationExpired()


def expire_idle_conversations(now=None, batch_size: int = 500) -> int:
    """Bulk job for cron: expire every idle conversation. Returns how many were expired."""
    idle = Conversation.objects.filter(
        status=Conversation.Status.ACTIVE, last_activity_at__lt=idle_cutoff(now)
    ).only("id", "status")
    count = 0
    for conversation in idle.iterator(chunk_size=batch_size):
        mark_expired(conversation)
        count += 1
    return count
