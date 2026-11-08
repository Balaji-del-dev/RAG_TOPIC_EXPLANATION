"""
The state LangGraph saves for every conversation (one checkpoint per step).

`messages` uses the add_messages reducer: a node returning messages appends them,
and returning RemoveMessage(id=...) deletes one. Every other field is simply
replaced by the latest value.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ConversationState(TypedDict, total=False):
    # Working memory: recent messages word for word (older ones live on as `summary`).
    messages: Annotated[list[AnyMessage], add_messages]
    summary: str

    # This turn
    question: str  # as the user typed it
    is_follow_up: bool
    follow_up_reasons: list[str]
    standalone_question: str  # what retrieval should search for
    resolution: str  # unchanged | llm | fallback
    summarized: bool  # did this turn summarise older messages?
    summary_method: str  # llm | fallback
    context_messages: list[AnyMessage]  # summary + recent history, within the token budget
    context_tokens: int
    answer: str
