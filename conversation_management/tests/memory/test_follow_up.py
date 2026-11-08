"""8. Follow-up question detection."""

import pytest

from conversation_memory.follow_up import detect_follow_up


def test_first_question_is_never_a_follow_up():
    result = detect_follow_up("And for part-time staff?", has_history=False)
    assert not result.is_follow_up


@pytest.mark.parametrize(
    "question, reason",
    [
        ("And for part-time staff?", "starts like a continuation"),
        ("What about maternity leave?", "starts like a continuation"),
        ("For managers?", "very short"),
        ("In Chennai?", "very short"),
        ("Is it paid?", "refers back with \"it\""),
        ("Can they carry it forward to next year?", "refers back with \"they\""),
        ("after probation ends?", "starts in the middle of a sentence"),
        ("Is there anything else I should know?", "compares with \"else\""),
    ],
)
def test_follow_ups(question, reason):
    result = detect_follow_up(question, has_history=True)
    assert result.is_follow_up
    assert any(r.startswith(reason) for r in result.reasons), result.reasons


@pytest.mark.parametrize(
    "question",
    [
        "How many sick days do I get?",
        "Is it possible to carry forward unused leave?",  # expletive "it"
        "What is the notice period for employees on probation?",
        "How do I apply for maternity leave in Chennai?",
        "When is the salary credited every month?",
    ],
)
def test_standalone_questions(question):
    assert not detect_follow_up(question, has_history=True).is_follow_up
