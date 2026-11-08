"""Web pages (Django templates): the playground and the "How it works" explainer."""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from conversations import explainer_content as content


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


EXAMPLES_FILE = Path(__file__).resolve().parent / "explainer_examples.json"


def how_it_works(request):
    """Plain-English explainer with a demo of real recorded results (public: no user data)."""
    parts = [dict(part) for part in content.PARTS]
    for index, part in enumerate(parts):
        part["previous"] = parts[index - 1] if index > 0 else None
        part["next"] = parts[index + 1] if index + 1 < len(parts) else None
    names = {part["number"]: part["name"] for part in parts}
    colours = {part["number"]: part["framework"] for part in parts}

    def chips(numbers):
        return [{"number": n, "name": names[n], "framework": colours[n]} for n in numbers]

    recorded = json.loads(EXAMPLES_FILE.read_text(encoding="utf-8"))
    return render(
        request,
        "conversations/how_it_works.html",
        {
            "parts": parts,
            "part_names": [{"number": p["number"], "name": p["name"], "framework": p["framework"]} for p in parts],
            "frameworks": content.FRAMEWORKS,
            "problems": [
                {"title": t, "example": e, "risk": r, "parts": chips(nums)} for t, e, r, nums in content.PROBLEMS
            ],
            "memory_comparison": content.MEMORY_COMPARISON,
            "journey": content.RAG_JOURNEY,
            "turn_flow": [{"title": t, "text": x, "parts": chips(nums)} for t, x, nums in content.TURN_FLOW],
            "design": content.DESIGN,
            "pitch": content.PITCH,
            "questions": content.QUESTIONS,
            "statuses": content.STATUSES,
            "fixes": content.FIXES,
            "scenarios": recorded["scenarios"],
            "recorded_on": recorded["recorded_on"],
            "recorded_llm": recorded["llm"],
            "idle_hours": settings.CONVERSATIONS["CONVERSATION_IDLE_HOURS"],
        },
    )
