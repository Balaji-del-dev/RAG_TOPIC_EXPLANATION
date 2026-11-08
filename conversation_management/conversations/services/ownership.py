"""
5. CONVERSATION OWNERSHIP VALIDATION                  (Django REST Framework + ORM)
==============================================================================

The problem
    Insecure Direct Object Reference (IDOR): user A changes the ID in the URL
    to user B's conversation and reads B's chat history, or adds messages to
    it. With HR questions about health, pay and complaints, that is a serious
    leak.

What it does
    Every read and write of a conversation goes through one function that only
    finds conversations owned by the signed-in user.

How it works
    1. The ID is validated first (conversation_ids.py).
    2. One query filters by BOTH id and owner:
           Conversation.objects.filter(owner=user).get(pk=id)
       There is no "load it, then check the owner" gap.
    3. Someone else's conversation raises the same 404 as a missing one, so an
       attacker cannot even learn that the ID exists.
    4. Defence in depth: the DRF permission IsConversationOwner checks
       obj.owner_id == request.user.id again on every object view.
    5. The LangGraph thread_id is never taken from the client. It is derived
       from the conversation after this check, so one user can never load
       another user's AI memory.
"""

from django.db.models import QuerySet

from conversations.exceptions import ConversationNotFound
from conversations.models import Conversation
from conversations.services.conversation_ids import parse_conversation_id


def owned_conversations(user) -> QuerySet[Conversation]:
    return Conversation.objects.filter(owner=user)


def get_owned_conversation(user, raw_id: object) -> Conversation:
    conversation_id = parse_conversation_id(raw_id)
    try:
        return owned_conversations(user).get(pk=conversation_id)
    except Conversation.DoesNotExist:
        raise ConversationNotFound()
