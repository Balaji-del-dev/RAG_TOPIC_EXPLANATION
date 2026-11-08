"""
8. FOLLOW-UP QUESTION DETECTION                                   (LangGraph node)
==============================================================================

The problem
    "How many sick days do I get?"  ->  "And for part-time staff?"
    The second question means nothing on its own. If it is sent to retrieval as
    typed, the search finds random documents about "part-time staff".

What it does
    Decides, cheaply and without an LLM, whether the new question leans on the
    earlier conversation. Only follow-ups are sent to the LLM rewriter (step 7),
    so ordinary questions cost no extra LLM call.

How it works (rules, in this order)
    1. No earlier question in the conversation      -> not a follow-up.
    2. Starts like a continuation                   "and ...", "what about ...", "also ..."
    3. Very short (4 words or fewer)                "For managers?"
    4. Starts in the middle of a sentence and short "in Chennai?", "after probation?"
    5. Refers back with a pronoun, if short         "is it paid?", "can they ..."
       Expletive "it" ("is it possible", "it is") does not count.
    6. Refers back with a comparison word, if short "what else", "any more", "instead"
    Any rule that matches makes it a follow-up, and the reasons are kept for the trace.

Why rules and not an LLM?
    About a microsecond, no cost, same answer every time, easy to explain. A
    false alarm only costs one extra rewrite: the rewriter is told to return a
    standalone question unchanged. A miss is the real risk, so the rules lean
    towards "yes".

Example
    history: "How many sick days do I get?"
    "And for part-time staff?" -> follow-up, reasons: starts like a continuation
"""

import re
from dataclasses import dataclass, field

CONTINUATION_START = re.compile(
    r"^(and|also|but|so|then|plus|or|what about|how about|what if|same for|and what|and how|"
    r"is that|does that|was that|are those|what else|anything else|any other)\b",
    re.IGNORECASE,
)
MID_SENTENCE_START = re.compile(
    r"^(for|in|with|without|after|before|during|on|at|from|to|by|under|over|per|if so|if not)\b",
    re.IGNORECASE,
)
REFERRING_WORD = re.compile(
    r"\b(it|its|it's|that|this|those|these|they|them|their|there|he|she|him|her|the same|such|the former|the latter)\b",
    re.IGNORECASE,
)
COMPARISON_WORD = re.compile(r"\b(else|more|another|instead|too|as well|either|other ones?|rest)\b", re.IGNORECASE)
# "it" that refers to nothing: "is it possible", "it is", "it's ok"
EXPLETIVE_IT = re.compile(
    r"\b(is it (possible|ok|okay|allowed|true|mandatory|necessary|required|compulsory|legal|fine)|it is|it's)\b",
    re.IGNORECASE,
)

SHORT = 4
FAIRLY_SHORT = 8
MEDIUM = 12


@dataclass(frozen=True)
class FollowUpResult:
    is_follow_up: bool
    reasons: list[str] = field(default_factory=list)


def detect_follow_up(question: str, has_history: bool) -> FollowUpResult:
    if not has_history:
        return FollowUpResult(False, ["first question in the conversation"])

    text = question.strip()
    words = re.findall(r"[\w'-]+", text)
    count = len(words)
    reasons: list[str] = []

    if CONTINUATION_START.search(text):
        reasons.append("starts like a continuation")
    if count <= SHORT:
        reasons.append(f"very short ({count} words)")
    if count <= FAIRLY_SHORT and MID_SENTENCE_START.search(text):
        reasons.append("starts in the middle of a sentence")
    if count <= MEDIUM:
        without_expletive = EXPLETIVE_IT.sub(" ", text)
        referring = REFERRING_WORD.search(without_expletive)
        if referring:
            reasons.append(f"refers back with \"{referring.group(0).lower()}\"")
        comparison = COMPARISON_WORD.search(text)
        if comparison:
            reasons.append(f"compares with \"{comparison.group(0).lower()}\"")

    return FollowUpResult(bool(reasons), reasons)
