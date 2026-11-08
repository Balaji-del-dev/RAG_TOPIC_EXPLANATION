"""
The shared input_security pipeline for this Django process.

Built once per process (thread-safe) and reused by every request, because the
models inside it (fastText, spaCy, DeBERTa, FastEmbed) are expensive to load.
config/wsgi.py calls get_pipeline() at startup when WARMUP_ON_STARTUP=true,
so the first user does not wait for the models to load.
"""

import threading

from django.conf import settings

from input_security import SecurityPipeline, build_pipeline

_pipeline: SecurityPipeline | None = None
_lock = threading.Lock()


def get_pipeline() -> SecurityPipeline:
    global _pipeline
    if _pipeline is None:
        with _lock:
            if _pipeline is None:
                pipeline = build_pipeline(settings.SECURITY_SETTINGS)
                if settings.SECURITY_SETTINGS.warmup_on_startup:
                    pipeline.warmup()
                _pipeline = pipeline
    return _pipeline
