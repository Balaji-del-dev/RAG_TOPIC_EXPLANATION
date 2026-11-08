"""
One chat turn, start to finish. All ten responsibilities, in order:

    2   get_or_start_session()      who is chatting, and which conversation is active   (Redis)
    1,5 get_owned_conversation()    valid ID, owned by this user, or 404                (DRF/ORM)
    10  ensure_writable()           not expired, or 410                                  (ORM)
        turn_lock()                 one answer at a time per conversation, or 409        (Redis)
    4   save_user_message()         the question is saved before the AI runs             (PostgreSQL)
    8,7,6,9 memory graph            follow-up? rewrite, fit the budget, summarise        (LangGraph + checkpointer)
    4   save_answer()               answer + follow-up details + summary                 (PostgreSQL)
    2   set_active_conversation()   the session now points at this conversation          (Redis)
    3   (the next history read refills the Redis cache)

One log line per turn records ids, decisions and timings, never the message text.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from langchain_core.messages import HumanMessage

from conversations.exceptions import ConversationBusy, ConversationExpired, ConversationNotFound, MemoryUnavailable
from conversations.models import Conversation, Message
from conversations.services import expiration, history, user_sessions
from conversations.services.memory import get_memory_graph
from conversations.services.ownership import get_owned_conversation

logger = logging.getLogger("conversations")

MEMORY_FIELDS = (
    "is_follow_up",
    "follow_up_reasons",
    "standalone_question",
    "resolution",
    "context_tokens",
    "summarized",
    "summary_method",
    "summary",
    "answer",
)


@dataclass
class TurnResult:
    conversation: Conversation
    user_message: Message
    assistant_message: Message
    memory: dict
    session: user_sessions.ChatSession
    session_started: bool
    new_conversation: bool


@contextmanager
def turn_lock(conversation_id):
    """Redis lock: two tabs sending at once would otherwise interleave the AI memory."""
    key = f"chat-turn-lock:{conversation_id}"
    token = uuid.uuid4().hex
    if not cache.add(key, token, timeout=settings.CONVERSATIONS["TURN_LOCK_SECONDS"]):
        raise ConversationBusy()
    try:
        yield
    finally:
        if cache.get(key) == token:
            cache.delete(key)


def _conversation_for_turn(user, conversation_id, session) -> tuple[Conversation, bool]:
    """The conversation to write in, and whether it was just created."""
    if conversation_id:  # the client chose one: it must be valid, owned and active
        conversation = get_owned_conversation(user, conversation_id)
        expiration.ensure_writable(conversation)
        return conversation, False

    if session.active_conversation_id:  # continue the session's conversation if still usable
        try:
            conversation = get_owned_conversation(user, session.active_conversation_id)
            expiration.ensure_writable(conversation)
            return conversation, False
        except (ConversationNotFound, ConversationExpired):
            pass  # deleted or expired since: start a fresh one

    return Conversation.objects.create(owner=user), True


def run_chat_turn(user, text: str, conversation_id: str | None = None) -> TurnResult:
    started = time.perf_counter()
    session, session_started = user_sessions.get_or_start_session(user)
    conversation, new_conversation = _conversation_for_turn(user, conversation_id, session)

    with turn_lock(conversation.id):
        user_message = history.save_user_message(conversation, text)
        try:
            state = get_memory_graph().invoke(
                # the memory message reuses the database id, so the two can be matched later
                {"question": text, "messages": [HumanMessage(content=text, id=str(user_message.id))]},
                config={"configurable": {"thread_id": conversation.thread_id}},
            )
        except Exception:
            history.mark_failed(user_message)
            logger.exception("chat_turn memory failed conversation=%s", conversation.pk)
            raise MemoryUnavailable()
        memory = {field: state.get(field) for field in MEMORY_FIELDS}
        assistant_message = history.save_answer(conversation, user_message, memory)

    session = user_sessions.set_active_conversation(user, conversation.id)
    conversation.refresh_from_db()
    logger.info(
        "chat_turn conversation=%s user=%s seq=%s follow_up=%s resolution=%s context_tokens=%s summarized=%s ms=%.0f",
        conversation.pk,
        user.pk,
        user_message.sequence,
        memory["is_follow_up"],
        memory["resolution"],
        memory["context_tokens"],
        memory["summarized"],
        (time.perf_counter() - started) * 1000,
    )
    return TurnResult(conversation, user_message, assistant_message, memory, session, session_started, new_conversation)
