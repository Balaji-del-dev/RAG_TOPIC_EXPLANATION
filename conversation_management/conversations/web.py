"""Playground page (Django template). It talks to the same REST API as any other client."""

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie


@login_required
@ensure_csrf_cookie
def playground(request):
    return render(
        request,
        "conversations/playground.html",
        {
            "session_minutes": settings.CONVERSATIONS["CHAT_SESSION_IDLE_SECONDS"] // 60,
            "idle_hours": settings.CONVERSATIONS["CONVERSATION_IDLE_HOURS"],
            "max_tokens": settings.CONVERSATION_MEMORY["MAX_CONTEXT_TOKENS"],
            "llm_model": settings.CONVERSATION_MEMORY["LLM_MODEL"] if settings.CONVERSATION_MEMORY["LLM_ENABLED"] else None,
        },
    )
