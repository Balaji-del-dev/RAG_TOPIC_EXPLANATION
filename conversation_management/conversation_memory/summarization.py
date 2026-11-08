"""
9. HISTORY SUMMARIZATION                                          (LangGraph node)
==============================================================================

The problem
    Cutting old messages (step 6) loses facts the user gave earlier: "I am a
    part-time employee in Chennai" said ten turns ago still matters.

What it does
    When the conversation is over the token budget, older messages are folded
    into a short running summary, and only the newest messages are kept word
    for word. The AI's memory stays small but keeps the important facts.

How it works
    1. Triggered by step 6 (needs_summary): over budget and more than
       KEEP_RECENT_MESSAGES messages.
    2. Split the messages into "old" and "recent". The cut moves forward so that
       the recent part starts with a user message, keeping question and answer
       pairs together.
    3. Ask the LLM to summarise the old messages together with the existing
       summary ("rolling summary"), in the third person, with one worked
       example. It keeps names, numbers, dates, topics and the user's goal,
       and adds nothing new.
    3b. Check the output. A reply containing "User:" / "Assistant:" lines is
       the model continuing the chat, not summarising it: qwen2.5:1.5b did
       exactly that and invented facts ("annual vacation days, typically...").
       Rejected output goes to the fallback, because a summary that invents
       facts is worse than none: later turns would treat them as true.
    4. Return the new summary, plus RemoveMessage(id=...) for every old message.
       LangGraph's add_messages reducer deletes them from the checkpointed state.
    5. If the LLM is down: an extractive fallback keeps the old summary and adds
       the user's earlier questions word for word (fail soft).

    The full transcript is never touched: Django/PostgreSQL keeps every message.
    Only the AI's working memory is compacted.

Example
    12 messages, 1,450 tokens, budget 1,200, keep 6
    -> summary: "The user is a part-time employee in Chennai asking about sick
       leave and carry-forward rules..." plus the last 6 messages
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger("conversation_memory")

import re

MAX_FALLBACK_CHARS = 800
MAX_SUMMARY_CHARS = 1000

SUMMARY_INSTRUCTIONS = (
    "You write a short summary of what an employee has told and asked an HR policy assistant.\n"
    "Rules:\n"
    "- Write 2 to 4 sentences in the third person, starting with \"The user\".\n"
    "- Keep only facts that appear in the conversation: the user's situation (role, location, "
    "employment type), names, numbers, dates, and the topics they asked about.\n"
    "- Do not answer the questions, do not add facts, do not continue the conversation.\n"
    "- Reply with the summary only.\n"
    "\n"
    "Example\n"
    "<conversation>\n"
    "User: I joined the Pune office last month as a contract designer.\n"
    "Assistant: Welcome! How can I help?\n"
    "User: Do contractors get paid holidays?\n"
    "</conversation>\n"
    "Summary: The user is a contract designer who joined the Pune office last month. "
    "They asked whether contractors get paid holidays."
)

# A "summary" that contains turns is the model continuing the chat, not summarising it.
LOOKS_LIKE_TRANSCRIPT = re.compile(r"^\s*(user|assistant)\s*:", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Summary:
    text: str
    method: str  # llm | fallback


def split_for_summary(messages: list[BaseMessage], keep_recent: int) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """Old messages to summarise, and recent ones to keep. Recent always starts with a user message."""
    cut = max(len(messages) - keep_recent, 0)
    while cut < len(messages) and not isinstance(messages[cut], HumanMessage):
        cut += 1
    return messages[:cut], messages[cut:]


def _render(messages: list[BaseMessage]) -> str:
    return "\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}" for m in messages
    )


def _clean(text: str) -> str:
    return re.sub(r"^\s*summary\s*:\s*", "", text.strip(), flags=re.IGNORECASE).strip()


def acceptable_summary(text: str) -> bool:
    return bool(text) and len(text) <= MAX_SUMMARY_CHARS and not LOOKS_LIKE_TRANSCRIPT.search(text)


def summarize_history(old_messages: list[BaseMessage], existing_summary: str, llm: BaseChatModel | None) -> Summary:
    if llm is not None:
        try:
            earlier = f"Earlier summary: {existing_summary}\n\n" if existing_summary else ""
            task = (
                f"{earlier}Summarise this conversation, including the earlier summary if there is one.\n"
                f"<conversation>\n{_render(old_messages)}\n</conversation>\nSummary:"
            )
            reply = llm.invoke([SystemMessage(content=SUMMARY_INSTRUCTIONS), HumanMessage(content=task)])
            text = _clean(str(reply.content))
            if acceptable_summary(text):
                return Summary(text, "llm")
            logger.warning("conversation_memory summary rejected (looks like a transcript or too long)")
        except Exception as exc:  # fail soft
            logger.warning("conversation_memory summary failed: %s", type(exc).__name__)

    questions = [str(m.content).strip() for m in old_messages if isinstance(m, HumanMessage)]
    added = "Earlier the user asked: " + " | ".join(questions) if questions else ""
    text = " ".join(part for part in (existing_summary, added) if part)
    return Summary(text[-MAX_FALLBACK_CHARS:], "fallback")
