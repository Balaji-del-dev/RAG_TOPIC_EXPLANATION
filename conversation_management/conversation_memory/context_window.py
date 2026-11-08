"""
6. CONTEXT WINDOW MANAGEMENT                                      (LangGraph node)
==============================================================================

The problem
    An LLM can only read a limited number of tokens, and every token costs money
    and time. A long conversation, sent in full every turn, eventually breaks
    the limit and gets slower and more expensive with every message.

What it does
    Keeps what the answer step receives (summary + recent messages + question)
    under a token budget (MAX_CONTEXT_TOKENS, default 1200). It also decides
    when older messages must be summarised (step 9).

How it works
    1. Count tokens with tiktoken (cl100k_base), plus about 4 tokens of overhead
       per message for the role and separators.
    2. needs_summary(): over budget, and more messages than KEEP_RECENT_MESSAGES?
       Then the graph goes to step 9 to summarise the older ones.
    3. build_context_window():
         - the running summary goes first, as a system message
         - then trim_messages(strategy="last") keeps the newest messages that
           still fit the remaining budget
         - the window always starts at a user message (start_on="human"), so it
           never begins with an answer whose question was cut off
    4. The token count is saved with the turn, so it can be watched in production.

Why count tokens and not messages?
    One message can be 5 tokens or 1,000. A "last 10 messages" rule either
    wastes the budget or overflows it.

Note
    cl100k_base is OpenAI's tokenizer. Other models count a little differently,
    so the budget is an estimate with a safety margin, not an exact limit.
"""

from __future__ import annotations

from functools import lru_cache

import tiktoken
from langchain_core.messages import BaseMessage, SystemMessage, trim_messages

MESSAGE_OVERHEAD_TOKENS = 4


@lru_cache(maxsize=1)
def _encoding():
    return tiktoken.get_encoding("cl100k_base")


def count_text_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def count_message_tokens(messages: list[BaseMessage]) -> int:
    return sum(count_text_tokens(str(m.content)) + MESSAGE_OVERHEAD_TOKENS for m in messages)


def summary_message(summary: str) -> SystemMessage:
    return SystemMessage(content=f"Summary of the earlier conversation: {summary}")


def count_context_tokens(messages: list[BaseMessage], summary: str) -> int:
    total = count_message_tokens(messages)
    if summary:
        total += count_message_tokens([summary_message(summary)])
    return total


def needs_summary(messages: list[BaseMessage], summary: str, max_tokens: int, keep_recent: int) -> bool:
    return len(messages) > keep_recent and count_context_tokens(messages, summary) > max_tokens


def build_context_window(history: list[BaseMessage], summary: str, max_tokens: int) -> list[BaseMessage]:
    """Summary first, then the newest history that fits in the budget."""
    window: list[BaseMessage] = []
    budget = max_tokens
    if summary:
        system = summary_message(summary)
        window.append(system)
        budget -= count_message_tokens([system])
    if budget <= 0 or not history:
        return window
    recent = trim_messages(
        history,
        max_tokens=budget,
        token_counter=count_message_tokens,
        strategy="last",
        start_on="human",
        allow_partial=False,
    )
    return window + list(recent)
