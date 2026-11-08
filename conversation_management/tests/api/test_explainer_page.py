"""The "How it works" page: public, complete, and its demo uses real recorded results."""

import json

import pytest

from conversations import explainer_content as content

PAGE = "/how-it-works"
NAMES = [
    "Conversation ID Validation", "User Session Retrieval", "Conversation History Retrieval",
    "Chat History Persistence", "Conversation Ownership Validation", "Context Window Management",
    "Previous Question Resolution", "Follow-up Question Detection", "History Summarization",
    "Session Expiration Handling",
]


@pytest.fixture
def page(client, db):
    return client.get(PAGE)


def test_public_and_explains_all_ten_parts_in_order(page):
    assert page.status_code == 200
    html = page.content.decode()
    positions = [html.index(f'id="lesson-{n}"') for n in range(1, 11)]
    assert positions == sorted(positions)
    for name in NAMES:
        assert name in html
    for framework in ["Django ORM / Django REST Framework", "LangGraph Checkpointer", "PostgreSQL / Redis"]:
        assert framework in html


def test_every_part_has_internals_and_interview_answers():
    assert [p["name"] for p in content.PARTS] == NAMES
    for part in content.PARTS:
        assert len(part["internals"]) >= 4, part["name"]
        assert len(part["questions"]) == 3, part["name"]
        assert part["summary"] and part["problem"] and part["limits"]


def test_page_sections(page):
    for text in ["Why is this needed?", "two kinds of memory", "Where it fits in the RAG chatbot",
                 "How one chat turn runs internally", "Explain your session and conversation management",
                 "What the API answers", "You are here"]:
        assert text in page.content.decode()


def test_demo_data_is_a_real_recording(page):
    scenarios = page.context["scenarios"]
    assert {s["id"] for s in scenarios} == {"follow_ups", "summary", "ownership", "session", "expired"}
    follow_ups = next(s for s in scenarios if s["id"] == "follow_ups")["entries"]
    assert follow_ups[1]["memory"]["is_follow_up"] is True
    ownership = next(s for s in scenarios if s["id"] == "ownership")["entries"]
    assert [e["status"] for e in ownership if e["type"] == "request"] == [404, 404, 404, 400, 200]
    summary = next(s for s in scenarios if s["id"] == "summary")["entries"]
    assert any(e["memory"]["summarized"] for e in summary)
    assert 'id="scenarios-data"' in page.content.decode()
