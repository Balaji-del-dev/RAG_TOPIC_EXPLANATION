"""DRF permission: the second ownership check (see services/ownership.py)."""

from rest_framework.permissions import BasePermission


class IsConversationOwner(BasePermission):
    message = "Conversation not found."

    def has_object_permission(self, request, view, obj) -> bool:
        return obj.owner_id == request.user.id
