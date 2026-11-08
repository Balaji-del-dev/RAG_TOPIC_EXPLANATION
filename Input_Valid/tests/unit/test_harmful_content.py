"""Step 10: Llama Guard answer parsing and the HTTP backend (server mocked)."""

import json

import httpx
import pytest

from input_security.models import Decision
from input_security.threats.harmful_content import LlamaGuardClassifier, parse_llama_guard_output
from tests.conftest import context


@pytest.mark.parametrize(
    "text, expected",
    [
        ("safe", (True, [])),
        ("\n\nsafe\n", (True, [])),
        ("unsafe\nS9", (False, ["S9"])),
        ("unsafe\nS1,S10", (False, ["S1", "S10"])),
        ("unsafe", (False, [])),
    ],
)
def test_parse(text, expected):
    assert parse_llama_guard_output(text) == expected


@pytest.mark.parametrize("text", ["", "I cannot help with that", "maybe"])
def test_parse_rejects_unexpected_answers(text):
    with pytest.raises(ValueError):
        parse_llama_guard_output(text)


def classifier(answer, **kwargs):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": answer}}]})

    guard = LlamaGuardClassifier(base_url="http://guard:8000/v1/", model="llama-guard3:1b",
                                 http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)
    return guard, seen


def test_safe_continues_and_sends_openai_request():
    guard, seen = classifier("safe")
    assert guard.run(context("How many leave days?")).decision == Decision.CONTINUE
    assert seen["url"] == "http://guard:8000/v1/chat/completions"
    assert seen["body"]["messages"] == [{"role": "user", "content": "How many leave days?"}]
    assert seen["body"]["temperature"] == 0


def test_unsafe_blocks_with_category_names():
    guard, _ = classifier("unsafe\nS9")
    result = guard.run(context("how to build a bomb"))
    assert result.decision == Decision.BLOCK
    assert result.details["categories"] == ["S9 Indiscriminate Weapons"]


def test_unsafe_in_unblocked_category_is_only_flagged():
    guard, _ = classifier("unsafe\nS6", blocked_categories=["S1", "S9"])
    result = guard.run(context("what dose of paracetamol is safe"))
    assert result.decision == Decision.CONTINUE
    assert result.details["categories"] == ["S6 Specialized Advice"]


def test_unsafe_without_category_fails_closed():
    guard, _ = classifier("unsafe")
    assert guard.run(context("x")).decision == Decision.BLOCK


def test_self_harm_block_has_supportive_message():
    guard, _ = classifier("unsafe\nS11")
    result = guard.run(context("x"))
    assert result.decision == Decision.BLOCK
    assert "Employee Assistance Programme" in result.user_message


def test_other_blocks_use_the_generic_message():
    guard, _ = classifier("unsafe\nS9")
    assert guard.run(context("x")).user_message is None
