"""
REST API (Django REST Framework). Every endpoint requires a signed-in user.

    GET    /api/v1/conversations/                  my conversations, newest first
    POST   /api/v1/conversations/                  start an empty conversation
    GET    /api/v1/conversations/{id}/             one conversation (404 if not mine)
    DELETE /api/v1/conversations/{id}/             delete transcript + AI memory
    GET    /api/v1/conversations/{id}/messages/    history (latest page cached; ?before=<sequence> for older)
    POST   /api/v1/conversations/{id}/messages/    send a message in this conversation
    GET    /api/v1/conversations/{id}/memory/      what the AI currently remembers
    POST   /api/v1/chat/                           send a message; continues the session's conversation
    GET    /api/v1/session/                        my chat session (from Redis)
    DELETE /api/v1/session/                        end my chat session
"""

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from conversations.permissions import IsConversationOwner
from conversations.serializers import (
    ChatRequestSerializer,
    ConversationSerializer,
    MessageSerializer,
    SendMessageSerializer,
    SessionSerializer,
)
from conversations.services import history, user_sessions
from conversations.services.chat_turn import TurnResult, run_chat_turn
from conversations.services.memory import memory_snapshot
from conversations.services.ownership import get_owned_conversation, owned_conversations


def session_payload(session: user_sessions.ChatSession) -> dict:
    data = {**session.__dict__, "expires_in_seconds": user_sessions.seconds_left(session)}
    data.pop("user_id", None)
    return SessionSerializer(data).data


def turn_payload(turn: TurnResult) -> dict:
    return {
        "conversation": ConversationSerializer(turn.conversation).data,
        "new_conversation": turn.new_conversation,
        "user_message": MessageSerializer(turn.user_message).data,
        "assistant_message": MessageSerializer(turn.assistant_message).data,
        "memory": {key: value for key, value in turn.memory.items() if key != "answer"},
        "session": {**session_payload(turn.session), "started_now": turn.session_started},
    }


class ConversationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated, IsConversationOwner]

    def get_queryset(self):
        return owned_conversations(self.request.user)  # 5: only ever my conversations

    def get_object(self):
        conversation = get_owned_conversation(self.request.user, self.kwargs["pk"])  # 1 + 5
        self.check_object_permissions(self.request, conversation)
        return conversation

    def perform_create(self, serializer):
        conversation = serializer.save(owner=self.request.user)
        user_sessions.set_active_conversation(self.request.user, conversation.id)

    def perform_destroy(self, instance):
        history.delete_conversation(self.request.user, instance)

    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        conversation = self.get_object()
        if request.method == "POST":
            body = SendMessageSerializer(data=request.data)
            body.is_valid(raise_exception=True)
            turn = run_chat_turn(request.user, body.validated_data["message"], conversation_id=str(conversation.id))
            return Response(turn_payload(turn), status=status.HTTP_201_CREATED)

        before = request.query_params.get("before")
        if before and before.isdigit():
            results = MessageSerializer(history.older_history(conversation, int(before)), many=True).data
        else:
            results = history.recent_history(conversation)  # 3: latest page, Redis-cached
        oldest = results[0]["sequence"] if results else None
        return Response({"results": results, "older_before": oldest if oldest and oldest > 1 else None})

    @action(detail=True, methods=["get"])
    def memory(self, request, pk=None):
        conversation = self.get_object()
        return Response({"conversation_id": str(conversation.id), **memory_snapshot(conversation.thread_id)})


class ChatView(APIView):
    """Send a message. Without conversation_id, continues the session's active conversation or starts one."""

    def post(self, request):
        body = ChatRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        conversation_id = body.validated_data.get("conversation_id")
        turn = run_chat_turn(
            request.user,
            body.validated_data["message"],
            conversation_id=str(conversation_id) if conversation_id else None,
        )
        return Response(turn_payload(turn), status=status.HTTP_201_CREATED)


class SessionView(APIView):
    def get(self, request):
        session = user_sessions.get_session(request.user)
        if session is None:
            return Response({"active": False, "detail": "No chat session. It expired or was never started."})
        return Response({"active": True, **session_payload(session)})

    def delete(self, request):
        user_sessions.end_session(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
