"""
Shared test helpers.

    tests/unit         pure logic, no model files (seconds)
    tests/integration  real fastText / spaCy / NeMo / FastEmbed; skipped if a model is missing
                       @pytest.mark.heavy -> LLM Guard DeBERTa, Llama Guard: RUN_HEAVY_TESTS=1
    tests/api          FastAPI service with a fake pipeline
"""

import os

import pytest

from input_security.models import Decision, ScanContext, StepResult


class FakeStep:
    """A pipeline step that returns a fixed result, for testing the pipeline and the APIs."""

    def __init__(self, number, decision=Decision.CONTINUE, *, text=None, enabled=True, raises=None,
                 reason="", user_message=None, tool="Fake"):
        self.number = number
        self.name = f"fake step {number}"
        self.tool = tool
        self.enabled = enabled
        self.decision = decision
        self.text = text
        self.raises = raises
        self.reason = reason
        self.user_message = user_message
        self.calls = 0

    def warmup(self):
        pass

    def run(self, ctx: ScanContext) -> StepResult:
        self.calls += 1
        if self.raises:
            raise self.raises
        return StepResult(self.decision, self.reason, text=self.text, user_message=self.user_message)


def context(text: str) -> ScanContext:
    return ScanContext(raw_query=text, query=text)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_HEAVY_TESTS") == "1":
        return
    skip_heavy = pytest.mark.skip(reason="loads a large model; run with RUN_HEAVY_TESTS=1")
    for item in items:
        if "heavy" in item.keywords:
            item.add_marker(skip_heavy)
