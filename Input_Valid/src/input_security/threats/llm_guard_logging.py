"""
Logging helpers.

LLM Guard logs with structlog straight to stdout, and its own configure_logger()
calls logging.basicConfig(), which would take over the root logger of the Django
or FastAPI app. Instead, structlog is pointed at the standard `logging` module
at WARNING level, so LLM Guard messages follow the host app's logging settings.
"""

import logging
import threading

_configured = False
_lock = threading.Lock()


def route_llm_guard_logs_to_stdlib(level: int = logging.WARNING) -> None:
    global _configured
    with _lock:
        if _configured:
            return
        import structlog

        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.KeyValueRenderer(key_order=["event"], drop_missing=True),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(level),
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        _configured = True
