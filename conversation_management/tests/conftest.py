"""
Shared fixtures.

    tests/memory   the LangGraph package alone: InMemorySaver and a fake LLM (no Django)
    tests/api      the whole service: real PostgreSQL test database (with LangGraph's
                   checkpoint tables from migration 0002), an in-process cache instead
                   of Redis, and a fake LLM or no LLM.
"""

import os

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

os.environ.setdefault("TIKTOKEN_CACHE_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache", "tiktoken"))


class BrokenLLM:
    """An LLM that is down."""

    def invoke(self, *args, **kwargs):
        raise TimeoutError("LLM did not answer")


@pytest.fixture
def fake_llm():
    def make(*responses):
        return FakeListChatModel(responses=list(responses))

    return make


@pytest.fixture
def memory_settings(settings):
    """Django-side memory settings: real PostgreSQL checkpointer, no LLM unless a test patches one in."""
    from conversations.services.memory import reset_memory_graph

    settings.CONVERSATION_MEMORY = {
        **settings.CONVERSATION_MEMORY,
        "LLM_ENABLED": False,
        "CHECKPOINTER": "postgres",
        "MAX_CONTEXT_TOKENS": 1200,
        "KEEP_RECENT_MESSAGES": 6,
    }
    reset_memory_graph()
    yield settings.CONVERSATION_MEMORY
    reset_memory_graph()


@pytest.fixture
def local_cache(settings):
    """In-process cache instead of Redis, emptied for every test."""
    from django.core.cache import cache

    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tests"}}
    cache.clear()
    yield cache
    cache.clear()


@pytest.fixture
def users(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user("alice", password="pw-alice-123"), User.objects.create_user("bob", password="pw-bob-123")


@pytest.fixture
def api(users, local_cache, memory_settings):
    """API clients signed in as alice and bob."""
    from rest_framework.test import APIClient

    alice, bob = users
    clients = {}
    for user in (alice, bob):
        client = APIClient()
        client.force_authenticate(user)
        clients[user.username] = client
    return clients


@pytest.fixture
def use_llm(settings, memory_settings, monkeypatch):
    """Turn the LLM on in the Django service, but answer with a fake one."""
    from conversations.services import memory

    def install(llm):
        settings.CONVERSATION_MEMORY = {**settings.CONVERSATION_MEMORY, "LLM_ENABLED": True}
        monkeypatch.setattr(memory, "create_chat_model", lambda **kwargs: llm)
        memory.reset_memory_graph()

    return install
