"""Whole turns through the API with the memory graph (6-9) and a fake LLM."""

from conversations.models import Conversation
from conversations.services.memory import memory_snapshot
from tests.api.helpers import chat, messages_url


def test_follow_up_is_rewritten_and_stored(api, use_llm, fake_llm):
    use_llm(fake_llm("How many sick days do part-time staff get?"))
    conversation_id = chat(api["alice"], "How many sick days do I get?").json()["conversation"]["id"]
    body = chat(api["alice"], "And for part-time staff?", conversation_id=conversation_id).json()

    assert body["memory"]["is_follow_up"] is True
    assert body["memory"]["resolution"] == "llm"
    assert body["memory"]["standalone_question"] == "How many sick days do part-time staff get?"
    assert body["user_message"]["content"] == "And for part-time staff?"  # original text is kept
    assert body["user_message"]["standalone_question"] == "How many sick days do part-time staff get?"


def test_without_llm_the_chat_still_works(api):
    conversation_id = chat(api["alice"], "How many sick days do I get?").json()["conversation"]["id"]
    body = chat(api["alice"], "And for part-time staff?", conversation_id=conversation_id).json()
    assert body["memory"]["resolution"] == "fallback"


def test_long_conversation_is_summarised(api, use_llm, fake_llm, settings):
    settings.CONVERSATION_MEMORY = {**settings.CONVERSATION_MEMORY, "MAX_CONTEXT_TOKENS": 90, "KEEP_RECENT_MESSAGES": 2}
    use_llm(fake_llm("Employee asked about annual, maternity and carry-forward leave."))
    conversation_id = None
    for question in [
        "How many annual leave days do employees get each year in the Chennai office?",
        "What is the policy for carrying forward unused annual leave to the next year?",
        "How do I apply for maternity leave and which documents does HR need from me?",
    ]:
        body = chat(api["alice"], question, conversation_id=conversation_id).json()
        conversation_id = body["conversation"]["id"]

    assert body["memory"]["summarized"] is True
    assert body["memory"]["context_tokens"] <= 90
    assert Conversation.objects.get(pk=conversation_id).summary.startswith("Employee asked about")
    assert memory_snapshot(conversation_id)["messages_in_memory"] <= 3  # AI memory compacted
    assert len(api["alice"].get(messages_url(conversation_id)).json()["results"]) == 6  # transcript is not


def test_memory_endpoint(api):
    conversation_id = chat(api["alice"], "How many sick days do I get?").json()["conversation"]["id"]
    body = api["alice"].get(f"/api/v1/conversations/{conversation_id}/memory/").json()
    assert body["messages_in_memory"] == 2 and body["summary"] == ""
