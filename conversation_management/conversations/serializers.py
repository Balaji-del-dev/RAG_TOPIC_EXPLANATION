"""DRF serializers: request validation and response shapes."""

from django.conf import settings
from rest_framework import serializers

from conversations.models import Conversation, Message


class ConversationSerializer(serializers.ModelSerializer):
    expires_at = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "title", "status", "message_count", "summary", "created_at", "last_activity_at", "expires_at"]
        read_only_fields = fields

    def get_expires_at(self, conversation: Conversation) -> str:
        return conversation.expires_at().isoformat()


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id", "sequence", "role", "content", "status", "token_count",
            "is_follow_up", "standalone_question", "resolution", "created_at",
        ]
        read_only_fields = fields


class SendMessageSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=settings.CONVERSATIONS["MAX_MESSAGE_CHARS"], trim_whitespace=True)


class ChatRequestSerializer(SendMessageSerializer):
    # 1. Conversation ID validation in a request body: DRF rejects a malformed UUID with 400.
    conversation_id = serializers.UUIDField(required=False, allow_null=True, format="hex_verbose")


class SessionSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    active_conversation_id = serializers.CharField(allow_null=True)
    started_at = serializers.DateTimeField()
    last_seen_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    expires_in_seconds = serializers.IntegerField()
