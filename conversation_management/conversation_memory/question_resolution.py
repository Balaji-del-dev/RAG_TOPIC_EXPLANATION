"""
7. PREVIOUS QUESTION RESOLUTION                                   (LangGraph node)
==============================================================================

The problem
    A follow-up such as "And for part-time staff?" only makes sense next to the
    previous question. Retrieval needs one complete question to search with.

What it does
    Rewrites a follow-up into a standalone question, using the earlier
    conversation ("query rewriting" or "question condensing"):
        "How many sick days do I get?" + "And for part-time staff?"
        -> "How many sick days do part-time staff get?"
    The original text is still stored and shown. Only retrieval uses the rewrite.

How it works
    1. Runs only when step 8 said "follow-up".
    2. Builds a prompt: strict rules in the system message (keep the meaning,
       names and numbers; do not answer; return only the question), then two
       worked examples sent as real chat turns, then the running summary, the
       last few messages and the new question in the same format. Small models
       copy earlier turns far better than they follow rules: without examples,
       qwen2.5:1.5b turned "Can I take them in half days?" into "Can I take half
       days off?"; with the examples written inside the instructions, it echoed
       "And for part-time staff?" back unchanged.
    3. The LLM rewrites it at temperature 0.
    4. The output is cleaned (first line, no quotes or "Standalone question:"
       prefix) and checked: not empty, not too long, and still a question if
       the user asked one (a statement means the LLM answered instead of
       rewriting). An unchanged reply depends on how sure step 8 was: for a
       clearly incomplete question ("And for part-time staff?") it is a failure;
       for one flagged only by a pronoun ("Can they fire me during probation?")
       it means the LLM confirmed it is already standalone, and it is used as
       typed. A rejected rewrite is treated like a failure.
    5. If the LLM is down or the rewrite is rejected, a simple fallback joins
       the previous question and the follow-up. Retrieval still gets both
       topics, and the chat keeps working (fail soft).

Example
    history:  "How many sick days do I get?"
    question: "And for part-time staff?"
    -> "How many sick days do part-time staff get?"         (resolution: llm)
    -> "How many sick days do I get? And for part-time staff?" (resolution: fallback)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger("conversation_memory")

RECENT_MESSAGES_FOR_REWRITE = 6

REWRITE_INSTRUCTIONS = (
    "You rewrite follow-up questions for an HR policy assistant.\n"
    "Given the conversation, rewrite the user's latest question as ONE standalone question "
    "that can be understood without the conversation.\n"
    "Rules:\n"
    "- Keep the user's meaning, names, numbers and dates.\n"
    "- Replace words like it, that, they, there with what they refer to, and add the topic "
    "the question continues.\n"
    "- Do not answer the question. Do not add new facts.\n"
    "- Reply with the question only, on one line."
)

# Worked examples, sent as real chat turns in the same format as the actual request.
# Small models copy the format of previous turns far better than they follow examples
# described inside the instructions. Topics are deliberately different from any test question.
EXAMPLES = [
    (
        [("User", "How many days of paternity leave do fathers get?"), ("Assistant", "Fathers get 10 days of paternity leave.")],
        "Can I split it into two parts?",
        "Can paternity leave be split into two parts?",
    ),
    (
        [("User", "What is the monthly limit for mobile bill reimbursement?"), ("Assistant", "The limit is 1,000 rupees a month.")],
        "And for managers?",
        "What is the monthly limit for mobile bill reimbursement for managers?",
    ),
]


def _request(conversation: str, question: str) -> str:
    return f"Conversation:\n{conversation}\n\nLatest question: {question}\nStandalone question:"


def _example_turns() -> list:
    turns = []
    for history, question, rewrite in EXAMPLES:
        conversation = "\n".join(f"{speaker}: {text}" for speaker, text in history)
        turns += [HumanMessage(content=_request(conversation, question)), AIMessage(content=rewrite)]
    return turns


PREFIX = re.compile(r"^(standalone question|rewritten question|question|rewrite)\s*:\s*", re.IGNORECASE)


@dataclass(frozen=True)
class Resolution:
    question: str
    method: str  # unchanged | llm | fallback


def render_history(messages: list[BaseMessage], summary: str) -> str:
    lines = []
    if summary:
        lines.append(f"Summary of earlier conversation: {summary}")
    for message in messages[-RECENT_MESSAGES_FOR_REWRITE:]:
        speaker = "User" if isinstance(message, HumanMessage) else "Assistant"
        lines.append(f"{speaker}: {message.content}")
    return "\n".join(lines)


def _clean(text: str) -> str:
    first_line = next((line.strip() for line in text.strip().splitlines() if line.strip()), "")
    return PREFIX.sub("", first_line).strip().strip("\"'“”").strip()


def _same_text(a: str, b: str) -> bool:
    normalise = lambda text: re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return normalise(a) == normalise(b)


def _acceptable(rewrite: str, question: str) -> bool:
    if not rewrite or len(rewrite) > max(300, 4 * len(question)):
        return False
    # The user asked a question, so the rewrite must be one too. A statement here
    # usually means the LLM answered instead of rewriting.
    if "?" in question and "?" not in rewrite:
        return False
    return True


def _previous_question(history: list[BaseMessage]) -> str | None:
    for message in reversed(history):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return None


def resolve_question(
    question: str,
    history: list[BaseMessage],
    summary: str,
    llm: BaseChatModel | None,
    *,
    clearly_incomplete: bool = True,
) -> Resolution:
    """clearly_incomplete: step 8 saw a strong sign ("And for...?", very short, starts
    mid-sentence). Then the question cannot stand alone, so an unchanged rewrite is
    a failure. With only weak signs (a pronoun such as "they"), an unchanged rewrite
    means the LLM judged the question already standalone, and it is used as typed."""
    if llm is not None:
        try:
            reply = llm.invoke(
                [SystemMessage(content=REWRITE_INSTRUCTIONS), *_example_turns(),
                 HumanMessage(content=_request(render_history(history, summary), question))]
            )
            rewrite = _clean(str(reply.content))
            if _same_text(rewrite, question):
                # Echoing "And for part-time staff?" would make retrieval search for
                # part-time staff with no topic; echoing "Can they fire me during
                # probation?" is the LLM saying it is already complete.
                if not clearly_incomplete:
                    return Resolution(question, "unchanged")
                logger.warning("conversation_memory rewrite rejected (echo of a clearly incomplete question)")
            elif _acceptable(rewrite, question):
                return Resolution(rewrite, "llm")
            logger.warning("conversation_memory rewrite rejected (length %d)", len(rewrite))
        except Exception as exc:  # LLM down, timeout, bad response: fail soft
            logger.warning("conversation_memory rewrite failed: %s", type(exc).__name__)

    previous = _previous_question(history)
    if previous:
        joined = f"{previous.rstrip()} {question.strip()}"
        return Resolution(joined, "fallback")
    return Resolution(question, "unchanged")
