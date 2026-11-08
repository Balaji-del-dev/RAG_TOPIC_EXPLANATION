# RAG_TOPIC_EXPLANATION

Production-style implementations of the stages of a RAG (Retrieval-Augmented
Generation) chatbot, each with simple, interview-ready explanations.

## Topics

| Folder | Stage | What it contains |
|---|---|---|
| [Input_Valid](Input_Valid/) | 3. Input validation & security | 11 checks (Pydantic, fastText, NeMo Guardrails, Microsoft Presidio, Microsoft Purview, LLM Guard, Llama Guard) in one Python package, served by FastAPI and Django, plus a "How it works" page with a live demo and interview questions |
| [conversation_management](conversation_management/) | 4. Session & conversation management | Django ORM / DRF conversations and transcript, LangGraph checkpointer memory (follow-up detection, question rewriting, token budget, summaries), PostgreSQL + Redis (sessions, expiry, cache), playground page |

## Quick start (Input_Valid)

```bash
cd Input_Valid
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/bin/python -e ".[fastapi,django,dev]"
uv pip install --python .venv/bin/python pip
.venv/bin/python scripts/download_models.py

# Django: playground + "How it works" page
cd services/django_service && ../../.venv/bin/python manage.py runserver 127.0.0.1:8021
# open http://127.0.0.1:8021/how-it-works
```

The full guide is in [Input_Valid/README.md](Input_Valid/README.md).
