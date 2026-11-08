# Session & Conversation Management (stage 4)

Stage 4 of the RAG chatbot. It keeps track of **who is chatting**, **which conversation
they are in**, **everything that was said**, and what the AI should **remember** when it
answers the next question, including follow-ups like "And for part-time staff?".

| Layer | Framework | Keeps |
|---|---|---|
| API, data model, ownership | **Django ORM / Django REST Framework** | conversations and messages, the full transcript |
| AI working memory | **LangGraph checkpointer** (PostgresSaver) | recent messages and a running summary, per conversation |
| Storage | **PostgreSQL** | transcript and checkpoints (one database, separate tables) |
| Speed and expiry | **Redis** | chat sessions (TTL), login sessions, history cache, per-conversation lock |

The **transcript** (PostgreSQL via Django) is never trimmed: it is what the user sees and
audits read. The **AI memory** (LangGraph checkpointer) is kept small: older messages are
folded into a summary so the context stays within a token budget.

## The 10 responsibilities, one file each

| # | Responsibility | File | Framework |
|---|---|---|---|
| 1 | Conversation ID Validation | `conversations/services/conversation_ids.py` | DRF + ORM |
| 2 | User Session Retrieval | `conversations/services/user_sessions.py` | Redis |
| 3 | Conversation History Retrieval | `conversations/services/history.py` | ORM + Redis cache |
| 4 | Chat History Persistence | `conversations/services/history.py` | ORM → PostgreSQL |
| 5 | Conversation Ownership Validation | `conversations/services/ownership.py`, `permissions.py` | DRF + ORM |
| 6 | Context Window Management | `conversation_memory/context_window.py` | LangGraph |
| 7 | Previous Question Resolution | `conversation_memory/question_resolution.py` | LangGraph + LLM |
| 8 | Follow-up Question Detection | `conversation_memory/follow_up.py` | LangGraph |
| 9 | History Summarization | `conversation_memory/summarization.py` | LangGraph + LLM |
| 10 | Session Expiration Handling | `conversations/services/expiration.py`, `management/commands/expire_conversations.py` | Redis TTL + ORM |

Every file starts with a plain-English docstring: the problem it solves, how it works step
by step, and an example.

## One chat turn

```
POST /api/v1/chat/  {"message": "And for part-time staff?"}
  2   session from Redis           which conversation is active?          (sliding 30-min TTL)
  1,5 conversation lookup          valid uuid4 AND owned by me, else 404
  10  writable?                    idle > 24 h → 410 Gone (history still readable)
      Redis lock                   one answer at a time per conversation, else 409
  4   save question (pending)      PostgreSQL, row lock, next sequence number
  ── LangGraph (thread_id = conversation id, state loaded from the checkpointer) ──
  8   detect_follow_up             rules: "starts like a continuation", "very short"…
  7   resolve_question             LLM: "How many sick days do part-time staff get?"
  6   over token budget?           yes → 9 summarize_history (old messages → summary)
  6   build_context                summary + newest history within MAX_CONTEXT_TOKENS
      answer                       ← the retrieval + generation stage plugs in here
  ── state saved by the checkpointer after every step ──
  4   save answer                  + is_follow_up, standalone_question, summary
  2   session points at this conversation
```

## Project layout

```
conversation_management/
├── manage.py, config/                Django project (django-admin startproject config .)
├── conversations/                    Django app (manage.py startapp conversations)
│   ├── models.py                     Conversation, Message
│   ├── services/                     responsibilities 1-5 and 10, plus chat_turn.py
│   ├── serializers.py, views.py, urls.py, permissions.py, exceptions.py
│   ├── management/commands/          create_demo_users, expire_conversations
│   ├── migrations/0002_…             creates LangGraph's checkpoint tables
│   └── templates/, static/           playground page (Django templates)
├── conversation_memory/              LangGraph package (no Django imports): responsibilities 6-9
├── tests/memory, tests/api           76 tests
├── docker-compose.yml                PostgreSQL 17 (port 5440) + Redis 7 (port 6390)
└── .env.example                      every setting
```

## Run it

```bash
cd conversation_management
docker compose up -d                                   # PostgreSQL + Redis
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python manage.py migrate                     # Django tables + LangGraph checkpoint tables
.venv/bin/python manage.py create_demo_users           # alice / bob, password demo-password-123
ollama pull qwen2.5:1.5b                               # LLM for rewriting and summaries (optional)
.venv/bin/python manage.py runserver 127.0.0.1:8040
```

Open **http://127.0.0.1:8040/how-it-works** for the plain-English explanation (a demo of real recorded conversations and a lesson with interview questions for each of the 10 parts), and **http://127.0.0.1:8040/** for the playground (sign in as `alice`). The admin is at `/admin/`.

Re-record the explanation page's demo after changing any rule: `python manage.py record_explainer_examples`.

```bash
TOKEN=$(.venv/bin/python manage.py create_demo_users | awk '/^alice/{print $3}' | cut -d= -f2)
curl -s -X POST http://127.0.0.1:8040/api/v1/chat/ -H "Authorization: Token $TOKEN" \
  -H 'Content-Type: application/json' -d '{"message": "How many sick days do I get?"}'
curl -s -X POST http://127.0.0.1:8040/api/v1/chat/ -H "Authorization: Token $TOKEN" \
  -H 'Content-Type: application/json' -d '{"message": "And for part-time staff?"}'
```

## API

| Method | Path | What it does |
|---|---|---|
| POST | `/api/v1/chat/` | send a message; continues the session's conversation or starts one |
| GET/POST | `/api/v1/conversations/` | list mine / start an empty one |
| GET/DELETE | `/api/v1/conversations/{id}/` | one conversation / delete transcript + AI memory |
| GET/POST | `/api/v1/conversations/{id}/messages/` | history (`?before=<sequence>` for older) / send |
| GET | `/api/v1/conversations/{id}/memory/` | what the AI remembers (summary, messages kept) |
| GET/DELETE | `/api/v1/session/` | my chat session / end it |

| Status | When |
|---|---|
| 400 | malformed `conversation_id` or message in the body |
| 404 | bad ID in the URL, missing, or **someone else's** (identical response) |
| 409 | the previous message in this conversation is still being answered |
| 410 | conversation expired (idle > 24 h): read-only |
| 503 | memory step failed; the question was saved as `failed` |

## Tests

```bash
.venv/bin/python -m pytest          # 76 tests: memory (fake LLM) + API (real PostgreSQL test database)
.venv/bin/python manage.py expire_conversations   # the cron job for responsibility 10
```

## Measured with the real LLM (qwen2.5:1.5b), and what was fixed

| Found | Fix |
|---|---|
| "Can I take them in half days?" became "Can I take half days off?" (lost what "them" meant) | worked examples in the prompt |
| With examples written inside the instructions, "And for part-time staff?" came back **unchanged** | examples sent as real chat turns; an echoed follow-up is rejected and the fallback is used |
| The summary continued the chat ("User: … Assistant: …") and **invented facts** | third-person format with an example; transcript-looking or overlong output is rejected and the extractive fallback is used |
| A statement returned instead of a question (the model answered instead of rewriting) | a rewrite must still be a question |

After the fixes: **8 of 8** real follow-ups were rewritten with the right topic (none of
them appear in the prompt), and summaries kept every fact (location, employment type,
topic) without inventing any. Larger models (qwen2.5:7b, GPT-4o-mini) are recommended in
production: the 1.5B model still sometimes shifts a question slightly ("Do I need my
manager to approve it?" → "Can … take casual leave … with the manager's approval?").

## Design choices worth knowing

- **Memory fails soft, security fails closed.** If the LLM is down, follow-ups are joined
  with the previous question and summaries become extractive, so the chat keeps working.
  Stage 3 (input security) refuses instead.
- **The question is saved before the AI runs**, so a crash never loses what the user typed.
- **thread_id is never taken from the client.** It is the conversation ID, used only after
  the ownership check, so one user can never load another user's AI memory.
- **Two expiry clocks.** A session (30 min, Redis TTL) is "this visit". A conversation
  (24 h, PostgreSQL) is "this topic".
- **Token counts are estimates.** tiktoken's cl100k_base differs slightly from other
  models' tokenizers, so the budget leaves a margin.
