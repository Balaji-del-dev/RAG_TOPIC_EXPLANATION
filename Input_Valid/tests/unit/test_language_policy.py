"""Step 5: the language rule (decide_language) without NeMo."""

from input_security.language.detection import LanguageResult
from input_security.language.policy import decide_language, language_names

ALLOWED = {"en"}


def test_allowed_and_confident():
    assert decide_language(LanguageResult("en", 0.95, [("en", 0.95)]), ALLOWED, 0.65)[0]


def test_other_language_is_refused():
    allowed, reason = decide_language(LanguageResult("fr", 0.99, [("fr", 0.99)]), ALLOWED, 0.65)
    assert not allowed and "'fr'" in reason


def test_too_short_is_allowed():
    assert decide_language(LanguageResult("und", 0.0, [], reliable=False), ALLOWED, 0.65)[0]


def test_uncertain_but_allowed_language_in_top_candidates():
    result = LanguageResult("es", 0.40, [("es", 0.40), ("en", 0.35), ("pt", 0.1)])
    assert decide_language(result, ALLOWED, 0.65)[0]


def test_uncertain_without_allowed_candidate_is_refused():
    result = LanguageResult("de", 0.50, [("de", 0.50), ("nl", 0.3), ("da", 0.1)])
    assert not decide_language(result, ALLOWED, 0.65)[0]


def test_language_names():
    assert language_names(["en", "ta"]) == "English, Tamil"
