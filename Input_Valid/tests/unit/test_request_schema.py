"""Steps 1-2: Pydantic request schema and size limits."""

import pytest
from pydantic import ValidationError

from input_security.validation.request_schema import ChatRequest, explain_errors
from input_security.validation.size_limits import MAX_QUERY_BYTES, MAX_QUERY_CHARS, body_too_large


def errors_for(payload):
    with pytest.raises(ValidationError) as exc:
        ChatRequest.model_validate(payload)
    return explain_errors(exc.value.errors())


def test_valid_request():
    request = ChatRequest.model_validate({"query": "How many annual leave days do employees get?", "session_id": "abc-123"})
    assert request.query.startswith("How many")


@pytest.mark.parametrize(
    "payload, error_type",
    [
        ({}, "missing"),
        ({"query": ""}, "string_too_short"),
        ({"query": "   \n\t "}, "query_blank"),
        ({"query": 42}, "string_type"),
        ({"query": None}, "string_type"),
        ({"query": ["a"]}, "string_type"),
        ({"query": "hi there", "role": "admin"}, "extra_forbidden"),
        ({"query": "hi there", "session_id": "bad id!"}, "string_pattern_mismatch"),
    ],
)
def test_step1_rejects_bad_shape(payload, error_type):
    errors = errors_for(payload)
    assert error_type in {e["type"] for e in errors}
    assert all(e["step"] == 1 for e in errors)


def test_step2_rejects_too_many_characters():
    errors = errors_for({"query": "a" * (MAX_QUERY_CHARS + 1)})
    assert errors[0]["type"] == "string_too_long" and errors[0]["step"] == 2


def test_step2_rejects_too_many_bytes():
    # 4-byte emoji: under the character limit, over the byte limit
    query = "😀" * (MAX_QUERY_BYTES // 4 + 1)
    assert len(query) <= MAX_QUERY_CHARS
    errors = errors_for({"query": query})
    assert errors[0]["type"] == "query_too_many_bytes" and errors[0]["step"] == 2


def test_errors_never_echo_the_input():
    errors = errors_for({"query": "x" * (MAX_QUERY_CHARS + 1)})
    assert "x" * 50 not in str(errors)


def test_body_size_limit():
    assert body_too_large(40_000, limit=32_768)
    assert not body_too_large(100, limit=32_768)


def test_byte_limit_can_trigger_before_character_limit():
    # UTF-8 uses at most 4 bytes per character; a byte limit >= 4 x chars would be dead code.
    assert MAX_QUERY_BYTES < 4 * MAX_QUERY_CHARS


def test_full_length_tamil_query_is_allowed():
    query = ("விடுப்பு " * 500)[:MAX_QUERY_CHARS]
    assert ChatRequest.model_validate({"query": query})
