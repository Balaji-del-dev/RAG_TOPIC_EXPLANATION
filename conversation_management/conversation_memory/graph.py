"""
The conversation memory graph (LangGraph StateGraph), run once per chat turn.

    START
      -> detect_follow_up     8  is this question leaning on earlier ones?
      -> resolve_question     7  rewrite a follow-up into a standalone question
      -> (over token budget?) 6
           yes -> summarize_history   9  fold older messages into the summary
      -> build_context        6  summary + newest history that fits the budget
      -> answer                  next stage (retrieval + generation) plugs in here
    END

How memory survives between turns
    The graph is compiled with a checkpointer. Every call passes
    config={"configurable": {"thread_id": <conversation id>}}. LangGraph loads
    the last saved state of that thread (messages + summary), runs the steps,
    and saves the new state after each step. Each conversation has its own
    memory, and it survives restarts and works across servers.

Usage
    graph = build_conversation_graph(checkpointer=..., llm=..., settings=MemorySettings())
    result = graph.invoke(
        {"question": text, "messages": [HumanMessage(content=text)]},
        config={"configurable": {"thread_id": str(conversation.id)}},
    )
    result["standalone_question"], result["answer"], result["context_tokens"], ...
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from conversation_memory.answer import Answerer, PlaceholderAnswerer
from conversation_memory.config import MemorySettings
from conversation_memory.context_window import (
    build_context_window,
    count_message_tokens,
    count_text_tokens,
    needs_summary,
)
from conversation_memory.follow_up import detect_follow_up
from conversation_memory.question_resolution import resolve_question
from conversation_memory.state import ConversationState
from conversation_memory.summarization import split_for_summary, summarize_history


def build_conversation_graph(
    *,
    checkpointer: BaseCheckpointSaver,
    llm: BaseChatModel | None = None,
    answerer: Answerer | None = None,
    settings: MemorySettings | None = None,
):
    settings = settings or MemorySettings()
    answerer = answerer or PlaceholderAnswerer()

    def history_before_this_question(state: ConversationState):
        # The new question was appended by the input, so it is the last message.
        return state["messages"][:-1]

    # 8 ----------------------------------------------------------------------
    def detect_follow_up_node(state: ConversationState) -> dict:
        history = history_before_this_question(state)
        has_history = any(isinstance(m, HumanMessage) for m in history) or bool(state.get("summary"))
        result = detect_follow_up(state["question"], has_history)
        return {
            "is_follow_up": result.is_follow_up,
            "follow_up_reasons": result.reasons,
            # reset the per-turn fields saved by the previous turn
            "summarized": False,
            "summary_method": "",
        }

    # 7 ----------------------------------------------------------------------
    def resolve_question_node(state: ConversationState) -> dict:
        if not state["is_follow_up"]:
            return {"standalone_question": state["question"], "resolution": "unchanged"}
        resolution = resolve_question(
            state["question"], history_before_this_question(state), state.get("summary", ""), llm
        )
        return {"standalone_question": resolution.question, "resolution": resolution.method}

    # 6: route ---------------------------------------------------------------
    def route_by_budget(state: ConversationState) -> str:
        over = needs_summary(
            state["messages"], state.get("summary", ""), settings.max_context_tokens, settings.keep_recent_messages
        )
        return "summarize_history" if over else "build_context"

    # 9 ----------------------------------------------------------------------
    def summarize_history_node(state: ConversationState) -> dict:
        old, _recent = split_for_summary(state["messages"], settings.keep_recent_messages)
        if not old:
            return {}
        summary = summarize_history(old, state.get("summary", ""), llm)
        return {
            "summary": summary.text,
            "summary_method": summary.method,
            "summarized": True,
            # add_messages deletes these from the saved state; the transcript in PostgreSQL keeps them
            "messages": [RemoveMessage(id=m.id) for m in old],
        }

    # 6: build the window ----------------------------------------------------
    def build_context_node(state: ConversationState) -> dict:
        question = state["standalone_question"]
        budget_for_history = settings.max_context_tokens - count_text_tokens(question)
        window = build_context_window(
            history_before_this_question(state), state.get("summary", ""), budget_for_history
        )
        return {
            "context_messages": window,
            "context_tokens": count_message_tokens(window) + count_text_tokens(question),
        }

    # next stage -------------------------------------------------------------
    def answer_node(state: ConversationState) -> dict:
        text = answerer.answer(state["standalone_question"], state["context_messages"])
        return {"answer": text, "messages": [AIMessage(content=text)]}

    builder = StateGraph(ConversationState)
    builder.add_node("detect_follow_up", detect_follow_up_node)
    builder.add_node("resolve_question", resolve_question_node)
    builder.add_node("summarize_history", summarize_history_node)
    builder.add_node("build_context", build_context_node)
    builder.add_node("answer", answer_node)

    builder.add_edge(START, "detect_follow_up")
    builder.add_edge("detect_follow_up", "resolve_question")
    builder.add_conditional_edges(
        "resolve_question", route_by_budget, {"summarize_history": "summarize_history", "build_context": "build_context"}
    )
    builder.add_edge("summarize_history", "build_context")
    builder.add_edge("build_context", "answer")
    builder.add_edge("answer", END)

    return builder.compile(checkpointer=checkpointer)
