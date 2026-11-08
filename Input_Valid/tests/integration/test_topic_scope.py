"""Step 11 with real NeMo Guardrails and the FastEmbed model."""

import pytest

from input_security.models import Decision
from input_security.scope.topic_scope import NemoTopicScope
from input_security.settings import get_settings
from tests.conftest import context

SETTINGS = get_settings()
pytestmark = pytest.mark.skipif(
    not SETTINGS.fastembed_cache_dir.exists(), reason="run scripts/download_models.py --only fastembed"
)


@pytest.fixture(scope="module")
def scope():
    return NemoTopicScope(SETTINGS.topic_embedding_model, SETTINGS.topic_min_similarity,
                          cache_dir=str(SETTINGS.fastembed_cache_dir))


@pytest.mark.parametrize(
    "text",
    [
        "How many annual leave days do employees get?",
        "Can I carry forward my unused leave?",
        "When will my salary be credited this month?",
        "What does the medical insurance cover for my parents?",
        "What is the notice period if I resign?",
        "How do I report harassment by a colleague?",
        "My email is <EMAIL_ADDRESS>. How many sick days do I get?",
    ],
)
def test_hr_questions_are_in_scope(scope, text):
    result = scope.run(context(text))
    assert result.decision == Decision.CONTINUE, result.details


@pytest.mark.parametrize(
    "text",
    [
        "Write me a poem about the ocean.",
        "What is the capital of Japan?",
        "Who will win the football world cup?",
        "Give me a recipe for paneer butter masala.",
        "Write a JavaScript function to reverse a string.",
    ],
)
def test_off_topic_is_redirected(scope, text):
    result = scope.run(context(text))
    assert result.decision == Decision.REDIRECT, result.details
    assert result.details["rail"] == "check topic scope"
    assert result.user_message.startswith("I can only help with HR policy questions")
