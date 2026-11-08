"""Steps 4-5 with the real fastText model and real NeMo Guardrails (no LLM needed)."""

import pytest

from input_security.language.detection import FastTextLanguageDetector
from input_security.language.policy import NemoLanguagePolicy
from input_security.models import Decision
from input_security.settings import get_settings
from tests.conftest import context

MODEL = get_settings().fasttext_model_path
pytestmark = pytest.mark.skipif(not MODEL.exists(), reason="run scripts/download_models.py --only fasttext")


@pytest.fixture(scope="module")
def detector():
    return FastTextLanguageDetector(MODEL)


@pytest.fixture(scope="module")
def policy():
    return NemoLanguagePolicy(["en"], 0.65)


@pytest.mark.parametrize(
    "text, language",
    [
        ("How many annual leave days do employees get?", "en"),
        ("Combien de jours de congé annuel ai-je par an ?", "fr"),
        ("எனக்கு எத்தனை விடுப்பு நாட்கள் உள்ளன?", "ta"),
        ("मुझे साल में कितनी छुट्टियाँ मिलती हैं?", "hi"),
    ],
)
def test_fasttext_detects(detector, text, language):
    assert detector.detect(text).language == language


def test_short_text_is_unreliable(detector):
    assert detector.detect("PTO?").reliable is False


@pytest.mark.parametrize(
    "text, decision",
    [
        ("How many annual leave days do employees get?", Decision.CONTINUE),
        ("Combien de jours de congé annuel ai-je par an ?", Decision.REJECT),
        ("leave policy?", Decision.CONTINUE),
    ],
)
def test_nemo_language_rail(detector, policy, text, decision):
    ctx = context(text)
    detector.run(ctx)
    result = policy.run(ctx)
    assert result.decision == decision
    if decision == Decision.REJECT:
        assert result.details["rail"] == "check language policy"
        assert result.user_message.startswith("Sorry, I can only answer questions written in English.")
