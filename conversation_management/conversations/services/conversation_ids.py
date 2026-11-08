"""
1. CONVERSATION ID VALIDATION                         (Django REST Framework + ORM)
==============================================================================

The problem
    Conversation IDs come from the client (URL or request body), so anything
    can arrive: "abc", "1", "../admin", a valid ID from someone else, or an
    ID typed in an unusual but legal way ("{...}", "urn:uuid:...") that would
    create a second cache key for the same conversation.

What it does
    Accepts only the form we create: a version-4 UUID written 8-4-4-4-12 with
    dashes (upper or lower case: RFC 4122 says UUIDs are case-insensitive).
    Anything else is treated as "not found".

How it works
    1. IDs are created by the database model as uuid4: 122 random bits, so
       they cannot be guessed or counted (unlike 1, 2, 3...).
    2. In a request body, DRF's UUIDField rejects a malformed ID with 400.
    3. In a URL, parse_conversation_id() parses it with Python's uuid module
       and checks that the version is 4 and the text is the plain 8-4-4-4-12
       form ("{...}", "urn:uuid:..." and dash-less forms are refused). A bad ID
       gives 404, exactly like an ID that does not exist.
    4. The parsed UUID is then looked up together with the owner
       (ownership.py), so validation and authorisation are one query.

Example
    "3f2b8c1e-...-4a7d"  (valid uuid4)  -> UUID, continue
    "3F2B8C1E-...-4A7D"  (upper case)   -> the same UUID
    "123", "abc", "{3f2b...}"           -> 404 Conversation not found
"""

import uuid

from conversations.exceptions import ConversationNotFound


def parse_conversation_id(raw: object) -> uuid.UUID:
    text = str(raw).strip()
    try:
        value = uuid.UUID(text)
    except (ValueError, AttributeError, TypeError):
        raise ConversationNotFound()
    if value.version != 4 or str(value) != text.lower():
        raise ConversationNotFound()
    return value
