"""
conversation_memory - the AI's working memory for each conversation (LangGraph).

One LangGraph run per chat turn, saved by a checkpointer under thread_id = conversation id:

    follow_up.py            8  Follow-up Question Detection
    question_resolution.py  7  Previous Question Resolution
    context_window.py       6  Context Window Management
    summarization.py        9  History Summarization
    graph.py                   wires the steps together into one LangGraph StateGraph
    checkpointer.py            PostgresSaver (production) / InMemorySaver (tests)
    answer.py                  where the next RAG stage (retrieval + generation) plugs in

The package does not import Django, so it can be used from any service.
"""

from conversation_memory.config import MemorySettings
from conversation_memory.graph import build_conversation_graph

__all__ = ["MemorySettings", "build_conversation_graph"]
