from django.contrib import admin

from conversations.models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ["sequence", "role", "content", "status", "is_follow_up", "standalone_question", "resolution"]
    readonly_fields = fields
    can_delete = False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "status", "message_count", "last_activity_at"]
    list_filter = ["status"]
    search_fields = ["title", "owner__username"]
    readonly_fields = ["id", "owner", "summary", "message_count", "created_at", "last_activity_at"]
    inlines = [MessageInline]
