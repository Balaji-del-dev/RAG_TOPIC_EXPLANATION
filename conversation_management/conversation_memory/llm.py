"""
The LLM used to rewrite follow-up questions (7) and summarise history (9).

Any OpenAI-compatible server works: Ollama for development, vLLM or OpenAI in
production. Only the base URL and model name change.

Both steps degrade gracefully: if the LLM is down they use a simpler method and
the chat keeps working. That is deliberate. Security checks fail closed, but
memory features fail soft, because a weaker rewrite is better than no answer.
"""

from langchain_core.language_models import BaseChatModel


def create_chat_model(*, base_url: str, model: str, api_key: str, timeout: float) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=base_url,
        model=model,
        api_key=api_key,
        temperature=0,  # same question, same rewrite
        timeout=timeout,
        max_retries=1,
    )
