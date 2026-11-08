"""10. Session expiration handling: idle conversations become read-only."""

from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from conversations.models import Conversation
from conversations.services.memory import memory_snapshot
from tests.api.helpers import chat, messages_url


def make_idle(conversation_id, hours=25):
    Conversation.objects.filter(pk=conversation_id).update(last_activity_at=timezone.now() - timedelta(hours=hours))


def test_idle_conversation_refuses_new_messages_but_keeps_history(api):
    conversation_id = chat(api["alice"], "How many sick days do I get?").json()["conversation"]["id"]
    make_idle(conversation_id)
    response = chat(api["alice"], "And for part-time staff?", conversation_id=conversation_id)
    assert response.status_code == 410
    assert Conversation.objects.get(pk=conversation_id).status == "expired"
    assert memory_snapshot(conversation_id)["messages_in_memory"] == 0  # AI memory deleted
    assert len(api["alice"].get(messages_url(conversation_id)).json()["results"]) == 2  # still readable


def test_session_pointing_at_an_expired_conversation_starts_a_new_one(api):
    first = chat(api["alice"], "How many sick days do I get?").json()["conversation"]["id"]
    make_idle(first)
    body = chat(api["alice"], "What is the notice period?").json()
    assert body["new_conversation"] is True and body["conversation"]["id"] != first


def test_bulk_expiry_command(api, capsys):
    idle = chat(api["alice"], "How many sick days do I get?").json()["conversation"]["id"]
    fresh = chat(api["bob"], "What is the notice period?").json()["conversation"]["id"]
    make_idle(idle)
    call_command("expire_conversations")
    assert "Expired 1 idle conversation" in capsys.readouterr().out
    assert Conversation.objects.get(pk=idle).status == "expired"
    assert Conversation.objects.get(pk=fresh).status == "active"
