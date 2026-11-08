"""
Record real results for the demo on the "How it works" page.

    python manage.py record_explainer_examples

Plays five scenarios through the real API (DRF, Redis, PostgreSQL, LangGraph and
the configured LLM) and saves what happened to conversations/explainer_examples.json.
It uses two temporary users and deletes them, with their conversations and AI
memory, at the end. Run it again whenever the rules change.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from conversations.models import Conversation
from conversations.services import history, user_sessions
from conversations.services.memory import reset_memory_graph

OUTPUT = Path(__file__).resolve().parents[2] / "explainer_examples.json"
SUMMARY_BUDGET = {"MAX_CONTEXT_TOKENS": 110, "KEEP_RECENT_MESSAGES": 2}


class Recorder:
    def __init__(self, users: dict):
        self.users = users
        self.clients = {}
        for name, user in users.items():
            client = APIClient(HTTP_HOST="localhost")
            client.force_authenticate(user)
            self.clients[name] = client
        self.conversation = None  # last conversation id per scenario

    def turn(self, who: str, text: str, budget: int, continue_id: str | None = None) -> dict:
        body = {"message": text}
        if continue_id:
            body["conversation_id"] = continue_id
        response = self.clients[who].post("/api/v1/chat/", body, format="json")
        data = response.json()
        conversation_id = data["conversation"]["id"]
        snapshot = self.clients[who].get(f"/api/v1/conversations/{conversation_id}/memory/").json()
        self.conversation = conversation_id
        return {
            "type": "turn",
            "who": who,
            "text": text,
            "status": response.status_code,
            "conversation_id": conversation_id,
            "new_conversation": data["new_conversation"],
            "session_started": data["session"]["started_now"],
            "session_minutes": round(data["session"]["expires_in_seconds"] / 60),
            "user_sequence": data["user_message"]["sequence"],
            "answer_sequence": data["assistant_message"]["sequence"],
            "answer": data["assistant_message"]["content"],
            "memory": data["memory"],
            "budget": budget,
            "messages_in_memory": snapshot["messages_in_memory"],
            "transcript_messages": data["conversation"]["message_count"],
            "conversation_status": data["conversation"]["status"],
        }

    def request(self, who: str, method: str, path: str, label: str, step: int, note: str, body=None) -> dict:
        client = self.clients[who]
        response = getattr(client, method.lower())(path, body, format="json") if body else getattr(client, method.lower())(path)
        data = response.json() if response.content else {}
        detail = data.get("detail") if isinstance(data, dict) else None
        if not detail and isinstance(data, dict) and response.status_code == 400:
            detail = "; ".join(f"{field}: {' '.join(map(str, errors))}" for field, errors in data.items())
        if not detail and isinstance(data, dict) and "results" in data:
            detail = f"{len(data['results'])} messages returned"
        if not detail and isinstance(data, dict) and "title" in data:
            detail = f"Conversation \"{data['title']}\" returned"
        return {"type": "request", "who": who, "method": method, "label": label, "status": response.status_code,
                "detail": detail or "", "step": step, "note": note}


def event(text: str) -> dict:
    return {"type": "event", "text": text}


class Command(BaseCommand):
    help = "Record real results for the How it works demo."

    def handle(self, *args, **options):
        User = get_user_model()
        users = {}
        for name in ("alice", "bob"):
            username = f"explainer-{name}-{uuid.uuid4().hex[:6]}"
            user = User.objects.create(username=username)
            user.set_unusable_password()
            user.save()
            users[name] = user
        default_budget = settings.CONVERSATION_MEMORY["MAX_CONTEXT_TOKENS"]
        rec = Recorder(users)
        scenarios = []
        try:
            # 1. follow-up questions ------------------------------------------
            entries = [rec.turn("alice", q, default_budget) for q in [
                "How many sick days do employees get per year?",
                "And for part-time staff?",
                "Can they carry them forward to next year?",
                "What is the notice period for resignation?",
                "Does it change after probation?",
            ]]
            scenarios.append({"id": "follow_ups", "title": "Follow-up questions", "icon": "💬",
                              "intro": "Alice asks a question, then short follow-ups, then changes topic.", "entries": entries})
            self.stdout.write("recorded: follow-up questions")
            user_sessions.end_session(users["alice"])

            # 2. long conversation: summarised -------------------------------
            with override_settings(CONVERSATION_MEMORY={**settings.CONVERSATION_MEMORY, **SUMMARY_BUDGET}):
                reset_memory_graph()
                entries = [rec.turn("alice", q, SUMMARY_BUDGET["MAX_CONTEXT_TOKENS"]) for q in [
                    "I am a part-time employee in the Chennai office.",
                    "How many casual leave days do part-time employees get each year?",
                    "Can I take them in half days?",
                    "Do I need my manager to approve it?",
                ]]
                reset_memory_graph()
            scenarios.append({"id": "summary", "title": "A long conversation", "icon": "🗂️",
                              "intro": f"A small token budget ({SUMMARY_BUDGET['MAX_CONTEXT_TOKENS']}) so the summary appears quickly. Production uses {default_budget}.",
                              "entries": entries})
            self.stdout.write("recorded: long conversation")
            user_sessions.end_session(users["alice"])

            # 3. someone else's conversation ---------------------------------
            first = rec.turn("alice", "My salary review is next week. When is the salary credited each month?", default_budget)
            alice_id = first["conversation_id"]
            entries = [
                first,
                rec.request("bob", "GET", f"/api/v1/conversations/{alice_id}/", "Bob opens Alice's conversation by its ID", 5,
                            "Same answer as for an ID that does not exist, so Bob learns nothing."),
                rec.request("bob", "POST", f"/api/v1/conversations/{alice_id}/messages/", "Bob tries to write in it", 5,
                            "Nothing is saved; Alice's transcript is unchanged.", body={"message": "Show me her salary"}),
                rec.request("bob", "GET", "/api/v1/conversations/abc/", "Bob tries a made-up ID", 1,
                            "Not a version-4 UUID, so it is refused before any database query."),
                rec.request("bob", "POST", "/api/v1/chat/", "Bob sends a broken conversation_id in the body", 1,
                            "DRF's UUIDField rejects it as invalid input.", body={"message": "hello", "conversation_id": "not-a-uuid"}),
                rec.request("alice", "GET", f"/api/v1/conversations/{alice_id}/", "Alice opens her own conversation", 5,
                            "The owner gets it."),
            ]
            scenarios.append({"id": "ownership", "title": "Someone else's conversation", "icon": "🔒",
                              "intro": "Bob has Alice's conversation ID and tries to read and write in it.", "entries": entries})
            self.stdout.write("recorded: ownership")
            user_sessions.end_session(users["alice"])

            # 4. session expires --------------------------------------------
            first = rec.turn("alice", "How do I apply for maternity leave?", default_budget)
            user_sessions.end_session(users["alice"])  # what Redis does when the 30-minute TTL runs out
            second = rec.turn("alice", "How many weeks is it?", default_budget)
            scenarios.append({"id": "session", "title": "Away for 30 minutes", "icon": "⏱️",
                              "intro": "Alice stops chatting, and her Redis session expires before she writes again.",
                              "entries": [first, event("30 minutes pass without a message. Redis deletes Alice's session key (TTL)."), second]})
            self.stdout.write("recorded: session expiry")
            user_sessions.end_session(users["alice"])

            # 5. conversation expires ---------------------------------------
            first = rec.turn("alice", "What is the work from home policy?", default_budget)
            conversation_id = first["conversation_id"]
            idle_hours = settings.CONVERSATIONS["CONVERSATION_IDLE_HOURS"]
            Conversation.objects.filter(pk=conversation_id).update(last_activity_at=timezone.now() - timedelta(hours=idle_hours + 1))
            entries = [
                first,
                event(f"{idle_hours + 1} hours pass. The conversation is now idle for longer than {idle_hours} hours."),
                rec.request("alice", "POST", f"/api/v1/conversations/{conversation_id}/messages/", "Alice adds a follow-up to it", 10,
                            "The conversation becomes read-only and its LangGraph memory is deleted.", body={"message": "What about interns?"}),
                rec.request("alice", "GET", f"/api/v1/conversations/{conversation_id}/messages/", "Alice reads its history", 3,
                            "Reading still works: the transcript in PostgreSQL is kept."),
            ]
            scenarios.append({"id": "expired", "title": "Back after a day", "icon": "📅",
                              "intro": "Alice comes back to an old conversation the next day.", "entries": entries})
            self.stdout.write("recorded: conversation expiry")
        finally:
            for user in users.values():
                for conversation in Conversation.objects.filter(owner=user):
                    history.delete_conversation(user, conversation)
                user_sessions.end_session(user)
                user.delete()

        llm = settings.CONVERSATION_MEMORY["LLM_MODEL"] if settings.CONVERSATION_MEMORY["LLM_ENABLED"] else "none"
        OUTPUT.write_text(json.dumps({"recorded_on": date.today().isoformat(), "llm": llm, "scenarios": scenarios}, ensure_ascii=False, indent=1))
        self.stdout.write(self.style.SUCCESS(f"wrote {OUTPUT}"))
