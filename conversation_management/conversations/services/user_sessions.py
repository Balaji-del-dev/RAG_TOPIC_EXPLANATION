"""
2. USER SESSION RETRIEVAL                                                 (Redis)
==============================================================================

The problem
    A chat app must know, on every message, who the user is and which
    conversation they are in right now, without hitting the main database on
    every request. API clients (mobile, other services) use tokens, not
    browser cookies, so Django's cookie session alone is not enough.

What it does
    Keeps one small "chat session" per user in Redis: a session ID, the
    active conversation, and when it started and was last seen. A message
    sent without a conversation ID continues the active conversation.

How it works
    1. Authentication (DRF token or login cookie) gives request.user.
    2. The session is stored under key chat-session:<user id> with a TTL of
       CHAT_SESSION_IDLE_SECONDS (default 30 minutes).
    3. get_or_start_session() reads it, or starts a new one if it is missing,
       then saves it again. Saving resets the TTL ("sliding expiration"), so an
       active user never times out and an idle one does.
    4. set_active_conversation() records the conversation the user just wrote in.
    5. Redis deletes the key by itself when the TTL runs out. See expiration.py.

Why Redis?
    It is read on every message: Redis answers in under a millisecond, and TTL
    expiry is built in, so no clean-up job is needed for sessions.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone


@dataclass
class ChatSession:
    session_id: str
    user_id: int
    active_conversation_id: str | None
    started_at: str
    last_seen_at: str
    expires_at: str


def _key(user_id: int) -> str:
    return f"chat-session:{user_id}"


def _idle_seconds() -> int:
    return settings.CONVERSATIONS["CHAT_SESSION_IDLE_SECONDS"]


def _save(session: ChatSession) -> ChatSession:
    now = timezone.now()
    session.last_seen_at = now.isoformat()
    session.expires_at = (now + timedelta(seconds=_idle_seconds())).isoformat()
    cache.set(_key(session.user_id), asdict(session), timeout=_idle_seconds())
    return session


def get_session(user) -> ChatSession | None:
    data = cache.get(_key(user.pk))
    return ChatSession(**data) if data else None


def get_or_start_session(user) -> tuple[ChatSession, bool]:
    """Return (session, started_now). Every call slides the expiry forward."""
    session = get_session(user)
    started = session is None
    if started:
        now = timezone.now().isoformat()
        session = ChatSession(
            session_id=uuid.uuid4().hex,
            user_id=user.pk,
            active_conversation_id=None,
            started_at=now,
            last_seen_at=now,
            expires_at=now,
        )
    return _save(session), started


def set_active_conversation(user, conversation_id) -> ChatSession:
    session, _ = get_or_start_session(user)
    session.active_conversation_id = str(conversation_id) if conversation_id else None
    return _save(session)


def clear_active_conversation_if(user, conversation_id) -> None:
    session = get_session(user)
    if session and session.active_conversation_id == str(conversation_id):
        session.active_conversation_id = None
        _save(session)


def end_session(user) -> None:
    cache.delete(_key(user.pk))


def seconds_left(session: ChatSession) -> int:
    expires = datetime.fromisoformat(session.expires_at)
    return max(int((expires - timezone.now()).total_seconds()), 0)
