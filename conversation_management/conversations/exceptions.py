"""Errors returned by the conversation API. DRF turns each into a JSON response."""

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException


class ConversationNotFound(APIException):
    # Also used for conversations owned by someone else: a 404 reveals nothing,
    # while a 403 would confirm that the conversation exists.
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Conversation not found."
    default_code = "conversation_not_found"


class ConversationExpired(APIException):
    status_code = status.HTTP_410_GONE
    default_code = "conversation_expired"

    def __init__(self):
        hours = settings.CONVERSATIONS["CONVERSATION_IDLE_HOURS"]
        super().__init__(
            f"This conversation ended after {hours} hours without activity. Its history is still "
            "readable. Start a new conversation to continue."
        )


class ConversationBusy(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The previous message in this conversation is still being answered. Try again in a moment."
    default_code = "conversation_busy"


class MemoryUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The conversation memory is temporarily unavailable. Your message was saved; please try again."
    default_code = "memory_unavailable"
