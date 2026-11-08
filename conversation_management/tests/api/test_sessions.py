"""2. User session retrieval (Redis) and 10. session expiry."""

from django.core.cache import cache

from tests.api.helpers import chat


def test_first_message_starts_a_session_and_a_conversation(api):
    body = chat(api["alice"], "How many sick days do I get?").json()
    assert body["session"]["started_now"] is True
    assert body["new_conversation"] is True
    assert body["session"]["active_conversation_id"] == body["conversation"]["id"]
    assert body["session"]["expires_in_seconds"] > 0


def test_next_message_without_an_id_continues_the_active_conversation(api):
    first = chat(api["alice"], "How many sick days do I get?").json()
    second = chat(api["alice"], "And for part-time staff?").json()
    assert second["session"]["started_now"] is False
    assert second["new_conversation"] is False
    assert second["conversation"]["id"] == first["conversation"]["id"]
    assert second["user_message"]["sequence"] == 3


def test_session_endpoint(api):
    assert api["alice"].get("/api/v1/session/").json()["active"] is False
    conversation_id = chat(api["alice"], "How many sick days do I get?").json()["conversation"]["id"]
    session = api["alice"].get("/api/v1/session/").json()
    assert session["active"] is True and session["active_conversation_id"] == conversation_id


def test_expired_session_starts_a_new_conversation(api, users):
    alice, _ = users
    first = chat(api["alice"], "How many sick days do I get?").json()
    cache.delete(f"chat-session:{alice.pk}")  # what Redis does when the TTL runs out
    after = chat(api["alice"], "What is the notice period?").json()
    assert after["session"]["started_now"] is True
    assert after["new_conversation"] is True
    assert after["conversation"]["id"] != first["conversation"]["id"]


def test_ending_the_session(api):
    chat(api["alice"], "How many sick days do I get?")
    assert api["alice"].delete("/api/v1/session/").status_code == 204
    assert api["alice"].get("/api/v1/session/").json()["active"] is False


def test_sessions_are_per_user(api):
    chat(api["alice"], "How many sick days do I get?")
    assert api["bob"].get("/api/v1/session/").json()["active"] is False
