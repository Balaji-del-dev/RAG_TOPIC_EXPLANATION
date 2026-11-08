"""9. History summarization."""

from langchain_core.messages import AIMessage, HumanMessage

from conversation_memory.summarization import split_for_summary, summarize_history
from tests.conftest import BrokenLLM

MESSAGES = [
    HumanMessage(content="I am a part-time employee in Chennai."),
    AIMessage(content="Noted."),
    HumanMessage(content="How many sick days do I get?"),
    AIMessage(content="6 days."),
    HumanMessage(content="Can I carry them forward?"),
    AIMessage(content="Up to 3."),
]


def test_recent_part_always_starts_with_a_user_message():
    old, recent = split_for_summary(MESSAGES, keep_recent=3)  # a plain cut would start at an answer
    assert isinstance(recent[0], HumanMessage)
    assert old + recent == MESSAGES


def test_llm_summary(fake_llm):
    summary = summarize_history(MESSAGES[:4], "", fake_llm("Part-time employee in Chennai asking about sick days."))
    assert summary.method == "llm" and "Chennai" in summary.text


def test_existing_summary_is_extended(fake_llm):
    llm = fake_llm("Updated summary.")
    summary = summarize_history(MESSAGES[2:4], "Part-time employee in Chennai.", llm)
    assert summary.text == "Updated summary."


def test_fallback_keeps_the_users_questions():
    summary = summarize_history(MESSAGES[:4], "Earlier summary.", BrokenLLM())
    assert summary.method == "fallback"
    assert summary.text.startswith("Earlier summary.")
    assert "part-time employee in Chennai" in summary.text and "sick days" in summary.text


def test_a_continued_conversation_is_not_accepted_as_a_summary(fake_llm):
    # what qwen2.5:1.5b produced before the fix: a made-up dialogue with invented facts
    invented = "User: I am looking for annual vacation days.\nAssistant: Part-time employees typically receive..."
    summary = summarize_history(MESSAGES[:4], "", fake_llm(invented))
    assert summary.method == "fallback"
    assert "typically" not in summary.text


def test_summary_prefix_is_removed(fake_llm):
    summary = summarize_history(MESSAGES[:4], "", fake_llm("Summary: The user is a part-time employee in Chennai."))
    assert summary.text == "The user is a part-time employee in Chennai."
