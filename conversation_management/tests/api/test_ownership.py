"""5. Conversation ownership validation (IDOR protection)."""

import uuid

from conversations.models import Conversation, Message
from tests.api.helpers import chat, conversation_url, messages_url


def alice_conversation(api) -> str:
    return chat(api["alice"], "My salary is confidential. When is it paid?").json()["conversation"]["id"]


def test_someone_elses_conversation_looks_exactly_like_a_missing_one(api):
    conversation_id = alice_conversation(api)
    theirs = api["bob"].get(conversation_url(conversation_id))
    missing = api["bob"].get(conversation_url(uuid.uuid4()))
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()


def test_cannot_read_write_or_delete_another_users_conversation(api):
    conversation_id = alice_conversation(api)
    bob = api["bob"]
    assert bob.get(messages_url(conversation_id)).status_code == 404
    assert bob.post(messages_url(conversation_id), {"message": "hi"}, format="json").status_code == 404
    assert chat(bob, "hi", conversation_id=conversation_id).status_code == 404
    assert bob.delete(conversation_url(conversation_id)).status_code == 404
    assert Conversation.objects.filter(pk=conversation_id).exists()
    assert Message.objects.filter(conversation_id=conversation_id).count() == 2  # nothing added by bob


def test_list_only_shows_my_conversations(api):
    alice_conversation(api)
    chat(api["bob"], "How many sick days do I get?")
    ids = [c["id"] for c in api["bob"].get("/api/v1/conversations/").json()["results"]]
    assert len(ids) == 1
    assert Conversation.objects.get(pk=ids[0]).owner.username == "bob"


def test_must_be_signed_in(users, local_cache):
    from rest_framework.test import APIClient

    assert APIClient().get("/api/v1/conversations/").status_code == 401
