"""
Where the next stage of the RAG chatbot plugs in.

This module prepares the question (standalone) and the context (summary +
recent history within the token budget). Retrieval and answer generation are
the next stages. Any object with an `answer()` method can be passed to
build_conversation_graph(answerer=...).
"""

from typing import Protocol

from langchain_core.messages import BaseMessage


class Answerer(Protocol):
    def answer(self, standalone_question: str, context: list[BaseMessage]) -> str: ...


class PlaceholderAnswerer:
    """Shows what the next stage would receive, until retrieval and generation are added."""

    def answer(self, standalone_question: str, context: list[BaseMessage]) -> str:
        return (
            "(Placeholder answer) The retrieval stage would now search the HR documents for: "
            f"\"{standalone_question}\""
        )
