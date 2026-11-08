"""
Connects Django to the LangGraph conversation memory (steps 6-9).

    get_memory_graph()   build the graph once per process: checkpointer + LLM + settings
    delete_memory(id)    drop a conversation's checkpointer thread (expiry, deletion)

The PostgreSQL checkpointer uses the same database as Django (its own tables),
through a separate psycopg connection pool, because LangGraph needs autocommit
connections. The LLM is optional: without it, rewriting and summarising fall
back to simpler methods (see conversation_memory/llm.py).
"""

from __future__ import annotations

import threading

from django.conf import settings
from django.db import connections

from conversation_memory import MemorySettings, build_conversation_graph
from conversation_memory.checkpointer import (
    create_memory_checkpointer,
    create_postgres_checkpointer,
    postgres_conninfo,
)
from conversation_memory.llm import create_chat_model

_lock = threading.Lock()
_graph = None
_checkpointer = None


def conninfo_for(alias: str = "default") -> str:
    """psycopg connection string for a Django database (the test database during tests)."""
    db = connections[alias].settings_dict
    return postgres_conninfo(host=db["HOST"], port=db["PORT"], dbname=db["NAME"], user=db["USER"], password=db["PASSWORD"])


def _build():
    config = settings.CONVERSATION_MEMORY
    if config["CHECKPOINTER"] == "memory":
        checkpointer = create_memory_checkpointer()
    else:
        checkpointer = create_postgres_checkpointer(conninfo_for())
    llm = None
    if config["LLM_ENABLED"]:
        llm = create_chat_model(
            base_url=config["LLM_BASE_URL"],
            model=config["LLM_MODEL"],
            api_key=config["LLM_API_KEY"],
            timeout=config["LLM_TIMEOUT_SECONDS"],
        )
    graph = build_conversation_graph(
        checkpointer=checkpointer,
        llm=llm,
        settings=MemorySettings(
            max_context_tokens=config["MAX_CONTEXT_TOKENS"],
            keep_recent_messages=config["KEEP_RECENT_MESSAGES"],
        ),
    )
    return graph, checkpointer


def get_memory_graph():
    global _graph, _checkpointer
    if _graph is None:
        with _lock:
            if _graph is None:
                _graph, _checkpointer = _build()
    return _graph


def get_checkpointer():
    get_memory_graph()
    return _checkpointer


def delete_memory(thread_id: str) -> None:
    get_checkpointer().delete_thread(thread_id)


def memory_snapshot(thread_id: str) -> dict:
    """What the AI currently remembers for a conversation (for the API and the playground)."""
    state = get_memory_graph().get_state({"configurable": {"thread_id": thread_id}}).values
    return {
        "summary": state.get("summary", ""),
        "messages_in_memory": len(state.get("messages", [])),
    }


def reset_memory_graph() -> None:
    """Forget the cached graph and close its connection pool (tests switch settings between runs)."""
    global _graph, _checkpointer
    with _lock:
        pool = getattr(_checkpointer, "conn", None)
        if pool is not None and hasattr(pool, "close"):
            pool.close()  # otherwise open connections block dropping the test database
        _graph, _checkpointer = None, None
