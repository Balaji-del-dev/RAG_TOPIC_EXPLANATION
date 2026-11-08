"""1. Conversation ID validation."""

import uuid

import pytest

from conversations.exceptions import ConversationNotFound
from conversations.services.conversation_ids import parse_conversation_id
from tests.api.helpers import chat, conversation_url


def test_valid_uuid4_is_accepted():
    value = uuid.uuid4()
    assert parse_conversation_id(str(value)) == value


def test_upper_case_is_the_same_id():
    # RFC 4122: UUIDs are case-insensitive. Cache keys use the database value, not the client's text.
    value = uuid.uuid4()
    assert parse_conversation_id(str(value).upper()) == value


@pytest.mark.parametrize(
    "raw",
    ["abc", "1", "", "../admin", str(uuid.uuid1()), "{%s}" % uuid.uuid4(), "urn:uuid:%s" % uuid.uuid4(), uuid.uuid4().hex],
)
def test_anything_else_is_not_found(raw):
    with pytest.raises(ConversationNotFound):
        parse_conversation_id(raw)


@pytest.mark.parametrize("raw", ["abc", "123", str(uuid.uuid1())])
def test_bad_id_in_url_gives_404(api, raw):
    response = api["alice"].get(conversation_url(raw))
    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found."}


def test_bad_id_in_body_gives_400(api):
    response = chat(api["alice"], "How many sick days do I get?", conversation_id="not-a-uuid")
    assert response.status_code == 400
    assert "conversation_id" in response.json()


def test_unknown_but_valid_id_gives_404(api):
    assert chat(api["alice"], "hello there", conversation_id=uuid.uuid4()).status_code == 404
