"""
LangGraph checkpointers: where the graph state of each conversation is saved.

A checkpointer stores a snapshot of the state after every graph step, keyed by
thread_id (= the conversation id). The next turn loads the latest snapshot, so
the graph "remembers" the conversation even after a restart or on another server.

    PostgresSaver  production: tables checkpoints, checkpoint_blobs,
                   checkpoint_writes and checkpoint_migrations, created by
                   setup_postgres_checkpointer() (run from a Django migration)
    InMemorySaver  tests: lost when the process stops
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def postgres_conninfo(*, host: str, port: str | int, dbname: str, user: str, password: str) -> str:
    return make_conninfo(host=host, port=str(port), dbname=dbname, user=user, password=password)


def create_postgres_checkpointer(conninfo: str, max_connections: int = 5) -> PostgresSaver:
    # PostgresSaver needs autocommit, no prepared statements and dict rows.
    pool = ConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=max_connections,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    return PostgresSaver(pool)


def setup_postgres_checkpointer(conninfo: str) -> None:
    """Create or upgrade LangGraph's checkpoint tables. Safe to run many times."""
    with PostgresSaver.from_conn_string(conninfo) as saver:
        saver.setup()


def create_memory_checkpointer() -> BaseCheckpointSaver:
    return InMemorySaver()
