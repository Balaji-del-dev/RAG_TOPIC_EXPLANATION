"""
Shared NeMo Guardrails helpers for step 5 (language policy) and step 11 (topic scope).

Why a background event loop?
    NeMo Guardrails is async. Django views are synchronous and FastAPI runs
    synchronous endpoints in worker threads, so there is no single event loop we
    can rely on. All NeMo work is sent to one long-lived loop running in a
    daemon thread. Each request waits for its own result, with a timeout.

How a rail is checked
    rails.check_async(messages, rail_types=[RailType.INPUT]) runs only the
    *input rails* of a config, without asking an LLM to answer. It returns a
    RailsResult:
        status  = passed | modified | blocked
        rail    = name of the flow that blocked (it called `stop`)
        content = the bot message the Colang flow chose (the refusal text)

    Values computed in Python (detected language, settings) are passed to the
    Colang flows as context variables through a {"role": "context"} message.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, Callable, Coroutine


class _BackgroundLoop:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(target=loop.run_forever, name="nemo-guardrails-loop", daemon=True)
                thread.start()
                self._loop = loop
        return self._loop

    def run(self, coroutine: Coroutine[Any, Any, Any], timeout: float) -> Any:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._ensure_started())
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise TimeoutError(f"NeMo Guardrails did not answer within {timeout} seconds")


NEMO_LOOP = _BackgroundLoop()


def load_rails(config_dir: Path, actions: dict[str, Callable[..., Any]], timeout: float):
    """Build LLMRails from a config folder and register the Python actions its flows call."""
    from nemoguardrails import LLMRails, RailsConfig

    async def _build():
        rails = LLMRails(RailsConfig.from_path(str(config_dir)))
        for action_name, function in actions.items():
            rails.register_action(function, name=action_name)
        return rails

    return NEMO_LOOP.run(_build(), timeout)


def check_input_rails(rails, user_message: str, context: dict[str, Any], timeout: float):
    """Run only the input rails. Returns NeMo's RailsResult."""
    from nemoguardrails.rails.llm.options import RailType

    messages = [
        {"role": "context", "content": context},
        {"role": "user", "content": user_message},
    ]
    return NEMO_LOOP.run(rails.check_async(messages, rail_types=[RailType.INPUT]), timeout)
