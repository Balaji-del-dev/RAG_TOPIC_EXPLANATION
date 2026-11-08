"""
3. CONVERSATION HISTORY RETRIEVAL                  (Django ORM + Redis cache)
4. CHAT HISTORY PERSISTENCE                         (Django ORM -> PostgreSQL)
==============================================================================

The problem
    Users expect to reopen a chat and see every message, in order, even after
    a restart. Messages must never be lost or numbered twice, even if two
    browser tabs send at the same moment. Showing the latest messages must be
    fast, because it happens every time a chat is opened.

What it does
    Retrieval: returns messages oldest-first. The latest page comes from a
    Redis cache; older pages come from PostgreSQL.
    Persistence: saves the user's question BEFORE the AI runs, and the answer
    after, both inside database transactions.

How persistence works (one turn)
    1. save_user_message():
         - BEGIN; lock the conversation row (SELECT ... FOR UPDATE)
         - next sequence = message_count + 1, saved as status "pending"
         - update message_count, last_activity_at and the title (first question)
         - COMMIT. The question is safe even if the AI step crashes next.
    2. The LangGraph memory runs (steps 6-9).
    3. save_answer(): lock the row again, mark the question "complete" with
       its follow-up details, add the assistant message, save the running
       summary, COMMIT.
    4. If the AI step fails: mark_failed() keeps the question as "failed",
       so the user can see it and try again.
    The unique (conversation, sequence) constraint is a second guard against
    two messages getting the same number.

How retrieval works (cache-aside)
    1. recent_history(): read key chat-history:<conversation id> from Redis.
    2. Miss: query the latest HISTORY_CACHE_SIZE messages (index on
       conversation + sequence), store them with a TTL, return them.
    3. Every write deletes the key (invalidate), so the next read is fresh.
    4. Older pages (?before=<sequence>) go to PostgreSQL directly; they are rare.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from conversation_memory.context_window import count_text_tokens
from conversations.models import Conversation, Message

TITLE_LENGTH = 60


def _cache_key(conversation_id) -> str:
    return f"chat-history:{conversation_id}"


def invalidate_history_cache(conversation_id) -> None:
    cache.delete(_cache_key(conversation_id))


# ---- 3. retrieval ----------------------------------------------------------

def recent_history(conversation: Conversation) -> list[dict]:
    """Latest messages, oldest first. Served from Redis when possible."""
    from conversations.serializers import MessageSerializer

    key = _cache_key(conversation.id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    size = settings.CONVERSATIONS["HISTORY_CACHE_SIZE"]
    latest = list(conversation.messages.order_by("-sequence")[:size])
    latest.reverse()
    data = MessageSerializer(latest, many=True).data
    cache.set(key, data, timeout=settings.CONVERSATIONS["HISTORY_CACHE_SECONDS"])
    return data


def older_history(conversation: Conversation, before_sequence: int, limit: int = 50) -> list[Message]:
    older = list(conversation.messages.filter(sequence__lt=before_sequence).order_by("-sequence")[:limit])
    older.reverse()
    return older


# ---- 4. persistence --------------------------------------------------------

def _make_title(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= TITLE_LENGTH else text[: TITLE_LENGTH - 1].rstrip() + "…"


@transaction.atomic
def save_user_message(conversation: Conversation, text: str) -> Message:
    locked = Conversation.objects.select_for_update().get(pk=conversation.pk)
    sequence = locked.message_count + 1
    message = Message.objects.create(
        conversation=locked,
        sequence=sequence,
        role=Message.Role.USER,
        content=text,
        status=Message.Status.PENDING,
        token_count=count_text_tokens(text),
    )
    locked.message_count = sequence
    locked.last_activity_at = timezone.now()
    fields = ["message_count", "last_activity_at"]
    if not locked.title:
        locked.title = _make_title(text)
        fields.append("title")
    locked.save(update_fields=fields)
    # Delete now, and again after COMMIT: a reader between the two could otherwise
    # re-cache the old page from a snapshot taken before this write.
    invalidate_history_cache(locked.pk)
    transaction.on_commit(lambda: invalidate_history_cache(locked.pk))
    return message


@transaction.atomic
def save_answer(conversation: Conversation, user_message: Message, memory: dict) -> Message:
    locked = Conversation.objects.select_for_update().get(pk=conversation.pk)

    user_message.status = Message.Status.COMPLETE
    user_message.is_follow_up = memory["is_follow_up"]
    user_message.standalone_question = memory["standalone_question"]
    user_message.resolution = memory["resolution"]
    user_message.save(update_fields=["status", "is_follow_up", "standalone_question", "resolution"])

    sequence = locked.message_count + 1
    answer = Message.objects.create(
        conversation=locked,
        sequence=sequence,
        role=Message.Role.ASSISTANT,
        content=memory["answer"],
        token_count=count_text_tokens(memory["answer"]),
    )
    locked.message_count = sequence
    locked.last_activity_at = timezone.now()
    locked.summary = memory.get("summary") or locked.summary
    locked.save(update_fields=["message_count", "last_activity_at", "summary"])
    # Delete now, and again after COMMIT: a reader between the two could otherwise
    # re-cache the old page from a snapshot taken before this write.
    invalidate_history_cache(locked.pk)
    transaction.on_commit(lambda: invalidate_history_cache(locked.pk))
    return answer


def mark_failed(user_message: Message) -> None:
    Message.objects.filter(pk=user_message.pk).update(status=Message.Status.FAILED)
    invalidate_history_cache(user_message.conversation_id)


def delete_conversation(user, conversation: Conversation) -> None:
    """Right to erasure: transcript, AI memory, cache and session pointer all go together."""
    from conversations.services.memory import delete_memory
    from conversations.services.user_sessions import clear_active_conversation_if

    conversation_id = conversation.pk
    delete_memory(conversation.thread_id)
    conversation.delete()  # messages are deleted by ON DELETE CASCADE
    invalidate_history_cache(conversation_id)
    clear_active_conversation_if(user, conversation_id)
