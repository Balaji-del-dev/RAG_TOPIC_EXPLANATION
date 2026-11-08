"""3. Conversation history retrieval and 4. chat history persistence."""

from unittest.mock import patch

from django.core.cache import cache

from conversations.models import Conversation, Message
from conversations.services.memory import memory_snapshot
from tests.api.helpers import chat, conversation_url, messages_url


def two_turns(api) -> str:
    conversation_id = chat(api["alice"], "How many sick days do I get?").json()["conversation"]["id"]
    chat(api["alice"], "And for part-time staff?", conversation_id=conversation_id)
    return conversation_id


def test_history_is_complete_and_in_order(api):
    conversation_id = two_turns(api)
    results = api["alice"].get(messages_url(conversation_id)).json()["results"]
    assert [m["sequence"] for m in results] == [1, 2, 3, 4]
    assert [m["role"] for m in results] == ["user", "assistant", "user", "assistant"]
    assert results[2]["is_follow_up"] is True
    assert results[2]["standalone_question"]  # what retrieval searched for


def test_latest_page_is_served_from_the_cache(api, django_assert_max_num_queries):
    conversation_id = two_turns(api)
    api["alice"].get(messages_url(conversation_id))  # fills the cache
    assert cache.get(f"chat-history:{conversation_id}") is not None
    with django_assert_max_num_queries(2):  # ownership lookup only, no message query
        api["alice"].get(messages_url(conversation_id))


def test_new_message_invalidates_the_cache(api):
    conversation_id = two_turns(api)
    api["alice"].get(messages_url(conversation_id))
    chat(api["alice"], "Is it paid?", conversation_id=conversation_id)
    assert cache.get(f"chat-history:{conversation_id}") is None
    assert len(api["alice"].get(messages_url(conversation_id)).json()["results"]) == 6


def test_older_pages(api):
    conversation_id = two_turns(api)
    older = api["alice"].get(messages_url(conversation_id) + "?before=3").json()["results"]
    assert [m["sequence"] for m in older] == [1, 2]


def test_question_is_saved_even_if_the_ai_step_fails(api):
    conversation_id = chat(api["alice"], "How many sick days do I get?").json()["conversation"]["id"]
    with patch("conversations.services.chat_turn.get_memory_graph") as graph:
        graph.return_value.invoke.side_effect = RuntimeError("model crashed")
        response = chat(api["alice"], "And for part-time staff?", conversation_id=conversation_id)
    assert response.status_code == 503
    saved = Message.objects.get(conversation_id=conversation_id, sequence=3)
    assert saved.status == Message.Status.FAILED and saved.content == "And for part-time staff?"
    assert not Message.objects.filter(conversation_id=conversation_id, sequence=4).exists()


def test_one_turn_at_a_time(api):
    conversation_id = chat(api["alice"], "How many sick days do I get?").json()["conversation"]["id"]
    cache.add(f"chat-turn-lock:{conversation_id}", "another-request", timeout=60)
    assert chat(api["alice"], "Is it paid?", conversation_id=conversation_id).status_code == 409


def test_delete_removes_transcript_memory_and_session_pointer(api):
    conversation_id = two_turns(api)
    assert memory_snapshot(conversation_id)["messages_in_memory"] == 4
    assert api["alice"].delete(conversation_url(conversation_id)).status_code == 204
    assert not Conversation.objects.filter(pk=conversation_id).exists()
    assert not Message.objects.filter(conversation_id=conversation_id).exists()
    assert memory_snapshot(conversation_id)["messages_in_memory"] == 0
    assert api["alice"].get("/api/v1/session/").json()["active_conversation_id"] is None
