"""6. Context window management."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from conversation_memory.context_window import (
    build_context_window,
    count_context_tokens,
    count_message_tokens,
    needs_summary,
)


def conversation(turns: int, words: int = 30):
    messages = []
    for i in range(turns):
        messages.append(HumanMessage(content=f"Question {i} " + "leave " * words))
        messages.append(AIMessage(content=f"Answer {i} " + "policy " * words))
    return messages


def test_tokens_are_counted_per_message_with_overhead():
    one = [HumanMessage(content="hello")]
    assert count_message_tokens(one) == 1 + 4


def test_summary_counts_towards_the_budget():
    messages = conversation(1)
    assert count_context_tokens(messages, "the user is in Chennai") > count_context_tokens(messages, "")


def test_needs_summary_only_when_over_budget_and_long_enough():
    messages = conversation(5)
    tokens = count_context_tokens(messages, "")
    assert needs_summary(messages, "", max_tokens=tokens - 1, keep_recent=6)
    assert not needs_summary(messages, "", max_tokens=tokens + 1, keep_recent=6)
    assert not needs_summary(messages[:4], "", max_tokens=1, keep_recent=6)  # too few messages to summarise


def test_window_keeps_the_newest_messages_within_budget():
    messages = conversation(6)
    window = build_context_window(messages, "", max_tokens=150)
    assert count_message_tokens(window) <= 150
    assert window[-1] is messages[-1]  # newest kept
    assert isinstance(window[0], HumanMessage)  # never starts with an orphan answer


def test_summary_goes_first():
    window = build_context_window(conversation(3), "The user is a part-time employee.", max_tokens=200)
    assert isinstance(window[0], SystemMessage)
    assert "part-time employee" in window[0].content
