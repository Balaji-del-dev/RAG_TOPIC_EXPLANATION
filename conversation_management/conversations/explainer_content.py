"""
Plain-English content for the "How it works" page (/how-it-works).

Edit the words here, not in the template. The demo uses real recorded results
(explainer_examples.json, made by `python manage.py record_explainer_examples`).
Colours follow the architecture diagram: blue = Django ORM / DRF,
green = LangGraph checkpointer, grey = PostgreSQL / Redis.
"""

FRAMEWORKS = {
    "blue": ("Django ORM / Django REST Framework", "API, data model, ownership, full transcript"),
    "green": ("LangGraph Checkpointer", "the AI's working memory: follow-ups, budget, summaries"),
    "grey": ("PostgreSQL / Redis", "where it is stored: transcript and checkpoints / sessions, cache, locks"),
}

PARTS = [
    {
        "number": 1,
        "name": "Conversation ID Validation",
        "framework": "blue",
        "tech": "DRF UUIDField + Python uuid",
        "file": "conversations/services/conversation_ids.py",
        "summary": "Makes sure a conversation ID is a real, well-formed ID before anything is looked up.",
        "problem": "IDs come from the client, so anything can arrive: \"abc\", \"1\", \"../admin\". With simple numbers (1, 2, 3...) anyone could guess other people's conversations.",
        "before": "GET /api/v1/conversations/abc/",
        "after": "404 \"Conversation not found.\" (no database query)",
        "after_state": "stopped",
        "internals": [
            ("Random, unguessable IDs", "Every conversation gets a version-4 UUID: 122 random bits, so IDs cannot be guessed or counted."),
            ("In a request body", "DRF's UUIDField rejects a malformed conversation_id with 400 and the field name."),
            ("In a URL", "parse_conversation_id() parses it with Python's uuid module and requires version 4 in the plain 8-4-4-4-12 form. Upper case is fine (RFC 4122); \"{...}\" and \"urn:uuid:\" forms are refused."),
            ("Same answer as \"missing\"", "A bad ID returns 404, exactly like an ID that does not exist, so it gives no hints."),
            ("Straight into the ownership check", "The parsed UUID goes into one query together with the owner (part 5)."),
        ],
        "questions": [
            ("Why UUIDs instead of auto-increment numbers?", "Numbers can be guessed (\"try 1042\") and leak how many conversations exist. Random UUIDs reveal nothing."),
            ("Why 404 and not 400 for a bad ID in the URL?", "To give an attacker no difference between \"badly formed\", \"does not exist\" and \"not yours\"."),
            ("Is an unguessable ID enough security?", "No. It only makes guessing hard. Access still needs the ownership check, because IDs can leak through logs, links or screenshots."),
        ],
        "limits": "It proves the format, not the permission. That is part 5's job.",
    },
    {
        "number": 2,
        "name": "User Session Retrieval",
        "framework": "grey",
        "tech": "Redis (key with a TTL)",
        "file": "conversations/services/user_sessions.py",
        "summary": "Finds who is chatting and which conversation they are in, in under a millisecond.",
        "problem": "Every message must know the user's active conversation. Mobile apps and other services use API tokens, not browser cookies, and reading the main database on every message is slow.",
        "before": "\"And for part-time staff?\" sent without a conversation ID",
        "after": "Redis session says: active conversation 83eb… → continue it",
        "after_state": "cleared",
        "internals": [
            ("Who is it?", "DRF authentication (API token or login cookie) gives request.user."),
            ("One small record per user", "Redis key chat-session:<user id> holds the session ID, active conversation, start time, last seen and expiry time."),
            ("Read or start", "get_or_start_session() reads it. If it is missing, a new session starts (started_now = true)."),
            ("Sliding expiry", "Every save sets the 30-minute TTL again, so an active user never times out and an idle one does."),
            ("Point at the conversation", "After the turn, set_active_conversation() saves which conversation the user is in."),
        ],
        "questions": [
            ("Why Redis and not the database?", "It is read on every message: Redis answers in under a millisecond and expires keys by itself, so no clean-up job is needed."),
            ("What if Redis restarts and loses sessions?", "Users simply start a new session. Sessions only hold pointers; the conversations and messages are safe in PostgreSQL."),
            ("One session per user or per device?", "Here it is per user, so two devices share the active conversation. For per-device sessions, key them by token or device ID."),
        ],
        "limits": "One session per user: two devices share the active conversation.",
    },
    {
        "number": 3,
        "name": "Conversation History Retrieval",
        "framework": "blue",
        "tech": "Django ORM + Redis cache",
        "file": "conversations/services/history.py",
        "summary": "Shows a conversation's messages, complete and in order, and fast.",
        "problem": "Opening a chat happens all the time. It must be fast and must never show messages out of order or miss one.",
        "before": "GET /api/v1/conversations/{id}/messages/ (second time)",
        "after": "Messages 1-4 oldest first, from the Redis cache (no message query)",
        "after_state": "cleared",
        "internals": [
            ("Cache-aside", "Look for key chat-history:<conversation id> in Redis first."),
            ("On a miss", "Query the latest 50 messages using the (conversation, sequence) index, store them for 5 minutes, and return them."),
            ("Never stale", "Every new message deletes the key right away and again after COMMIT, so the next read is fresh."),
            ("Older pages", "?before=<sequence> reads older messages straight from PostgreSQL; this is rarely needed."),
            ("Two kinds of history", "This API returns the full transcript for people. The AI's own memory for the next answer is loaded by the LangGraph checkpointer (parts 6-9)."),
        ],
        "questions": [
            ("Why delete the cache entry instead of updating it?", "It is simpler and always correct: the next read rebuilds it from the database."),
            ("Why delete it twice?", "A reader between the write and the COMMIT could cache the old page. Deleting again after the commit closes that gap."),
            ("Why page by sequence number, not page numbers?", "New messages would shift page numbers. \"Before sequence 51\" always means the same messages."),
        ],
        "limits": "Only the latest page is cached. Older pages always come from the database.",
    },
    {
        "number": 4,
        "name": "Chat History Persistence",
        "framework": "blue",
        "tech": "Django ORM → PostgreSQL",
        "file": "conversations/services/history.py",
        "summary": "Saves every question and answer permanently and in order, never losing or duplicating one.",
        "problem": "If the server crashes while the AI is answering, the question could be lost. Two browser tabs sending at the same moment could get the same message number. HR chats also need an audit trail.",
        "before": "\"And for part-time staff?\"",
        "after": "Saved as #3 (pending) → answer saved as #4, question marked complete",
        "after_state": "cleared",
        "internals": [
            ("Save the question first", "BEGIN, then lock the conversation row (SELECT ... FOR UPDATE). Sequence = count + 1, status \"pending\". COMMIT, all before the AI runs."),
            ("One answer at a time", "A Redis lock per conversation covers the whole AI step. A second request at the same time gets 409."),
            ("The AI step runs", "LangGraph parts 6-9."),
            ("Save the answer", "Lock the row again, mark the question complete with its follow-up details, add the answer as the next number, and copy the summary onto the conversation."),
            ("If the AI step fails", "The question is kept as \"failed\" and the API answers 503, so the user can see it and try again."),
            ("Last line of defence", "A UNIQUE (conversation, sequence) constraint in PostgreSQL."),
        ],
        "questions": [
            ("Why save the question before the AI runs?", "So a crash or timeout never loses what the user typed."),
            ("Why both a row lock and a Redis lock?", "The row lock keeps numbering correct inside short transactions. The Redis lock covers the whole AI step, which takes seconds, without keeping a database transaction open."),
            ("How is deleting a conversation handled?", "Right to erasure: transcript, AI memory (checkpointer thread), cache and the session pointer are all removed together."),
        ],
        "limits": "Answers are placeholders until the retrieval and generation stage is connected.",
    },
    {
        "number": 5,
        "name": "Conversation Ownership Validation",
        "framework": "blue",
        "tech": "DRF permission + owner-scoped query",
        "file": "conversations/services/ownership.py",
        "summary": "Makes sure you can only see and write in your own conversations.",
        "problem": "If Bob changes the ID in the URL, he must not read Alice's HR chat about health, pay or complaints. This is IDOR / Broken Object Level Authorization, number 1 on the OWASP API Security Top 10.",
        "before": "Bob: GET Alice's conversation",
        "after": "404, exactly the same answer as for an ID that does not exist",
        "after_state": "stopped",
        "internals": [
            ("One query, two conditions", "Conversation.objects.filter(owner=user).get(pk=id): ID and owner are checked together, so there is no \"load first, check later\" gap."),
            ("No existence leak", "Someone else's conversation raises the same 404 as a missing one."),
            ("Checked twice", "The DRF permission IsConversationOwner compares owner_id with request.user.id again (defence in depth)."),
            ("Lists are scoped", "\"My conversations\" only ever queries owner = me."),
            ("AI memory is protected too", "The LangGraph thread_id is the conversation ID, used only after this check. The client never chooses it."),
        ],
        "questions": [
            ("Why 404 and not 403?", "403 would confirm the conversation exists. 404 reveals nothing."),
            ("What is IDOR or BOLA?", "Accessing someone else's object by changing its ID in a request. It is the top API risk because it is easy to forget in a single endpoint."),
            ("Why check twice?", "If someone later writes a new endpoint and forgets the scoped query, the permission class still blocks it."),
        ],
        "limits": "Sharing a conversation with a colleague would need an explicit members table.",
    },
    {
        "number": 6,
        "name": "Context Window Management",
        "framework": "green",
        "tech": "LangGraph node + tiktoken + trim_messages",
        "file": "conversation_memory/context_window.py",
        "summary": "Keeps what the AI reads under a token budget, however long the chat gets.",
        "problem": "LLMs can only read a limited number of tokens. If the whole chat is sent every turn, each turn gets slower and more expensive, and eventually the limit breaks.",
        "before": "Turn 4 of a long chat: 107 tokens, budget 110",
        "after": "Over budget → summarised → 62 tokens",
        "after_state": "masked",
        "internals": [
            ("Count tokens", "tiktoken (cl100k_base) counts each message, plus about 4 tokens of overhead per message."),
            ("Check the budget", "MAX_CONTEXT_TOKENS (1200 in production; 110 in the demo so it triggers quickly)."),
            ("Over budget?", "If it is over budget and there are more than KEEP_RECENT_MESSAGES messages, the graph goes to History Summarization (part 9)."),
            ("Build the window", "Summary first, as a system message, then trim_messages(strategy=\"last\", start_on=\"human\") keeps the newest messages that fit."),
            ("Room for the question", "The standalone question's tokens are taken from the budget first."),
            ("Measured", "The token count is saved with every turn, so it can be monitored."),
        ],
        "questions": [
            ("Why count tokens and not messages?", "One message can be 5 tokens or 1,000. \"Last 10 messages\" either wastes the budget or overflows it."),
            ("Why must the window start with a user message?", "Otherwise it could begin with an answer whose question was cut off, which confuses the model."),
            ("Is cl100k_base exact for every model?", "No. Other models' tokenizers differ a little, so the budget is an estimate with a safety margin."),
        ],
        "limits": "One very long message can still crowd out the rest of the history.",
    },
    {
        "number": 7,
        "name": "Previous Question Resolution",
        "framework": "green",
        "tech": "LangGraph node + LLM (Ollama qwen2.5:1.5b)",
        "file": "conversation_memory/question_resolution.py",
        "summary": "Rewrites a follow-up into a complete question that retrieval can search for.",
        "problem": "\"And for part-time staff?\" means nothing to a search engine. It would find random documents about part-time staff.",
        "before": "\"And for part-time staff?\"",
        "after": "\"How many sick days do part-time staff get per year?\"",
        "after_state": "masked",
        "internals": [
            ("Only for follow-ups", "Runs only when part 8 says \"follow-up\", so other questions need no LLM call."),
            ("The prompt", "Rules in the system message, two worked examples sent as real chat turns, then the summary, the last 6 messages and the new question."),
            ("The LLM rewrites", "At temperature 0, so the same input always gives the same rewrite."),
            ("Check the rewrite", "Not empty, not too long, still a question (a statement means the model answered), and not an echo of a clearly incomplete follow-up."),
            ("Fail soft", "If the LLM is down or the rewrite is rejected, the follow-up is joined with the previous question, so retrieval still gets both topics."),
            ("Two texts kept", "The user sees what they typed; retrieval uses the rewrite. Both are stored."),
        ],
        "questions": [
            ("Why rewrite instead of sending the whole chat to retrieval?", "Embedding a whole conversation mixes topics. One focused question finds better documents."),
            ("Why send examples as chat turns?", "Measured: with the examples written inside the instructions, the small model echoed \"And for part-time staff?\" back unchanged. As chat turns, it rewrote 8 of 8 correctly."),
            ("What if the rewrite is wrong?", "The checks catch most failures, both texts are stored for review, and production should use a larger model."),
        ],
        "limits": "A 1.5B model sometimes shifts a question slightly. Use a larger model in production.",
    },
    {
        "number": 8,
        "name": "Follow-up Question Detection",
        "framework": "green",
        "tech": "LangGraph node (rules, no LLM)",
        "file": "conversation_memory/follow_up.py",
        "summary": "Decides cheaply whether a question leans on the earlier conversation.",
        "problem": "Calling the LLM for every question costs time and money. We only need to rewrite questions that depend on what came before.",
        "before": "\"And for part-time staff?\" / \"What is the notice period?\"",
        "after": "Follow-up (starts like a continuation, very short) / not a follow-up",
        "after_state": "cleared",
        "internals": [
            ("First question?", "With no earlier question it can never be a follow-up."),
            ("Strong signs", "Starts like a continuation (\"and...\", \"what about...\"), very short (4 words or fewer), or starts mid-sentence (\"for managers?\")."),
            ("Weak signs, short questions only", "A pronoun such as \"it\" or \"they\" (expletive \"it is\" and \"is it possible\" are ignored), or a comparison word (\"else\", \"instead\")."),
            ("Decide and explain", "Any sign makes it a follow-up, and the reasons are saved for the trace and the logs."),
            ("Strong vs weak", "With only weak signs, the LLM may answer \"already complete\", and the question is used as typed."),
        ],
        "questions": [
            ("Why rules and not an LLM?", "Microseconds, free, the same answer every time, and easy to explain. The LLM is only needed for the rewrite itself."),
            ("Which mistake is worse?", "A missed follow-up: retrieval searches the wrong thing. A false alarm only costs one rewrite, so the rules lean towards \"yes\"."),
            ("How do you improve the rules?", "Log the reasons, review missed follow-ups from real conversations, and add them as test cases."),
        ],
        "limits": "Unusual phrasing without any sign can be missed.",
    },
    {
        "number": 9,
        "name": "History Summarization",
        "framework": "green",
        "tech": "LangGraph node + LLM + RemoveMessage",
        "file": "conversation_memory/summarization.py",
        "summary": "Folds older messages into a short summary, so the AI keeps key facts without re-reading everything.",
        "problem": "Just cutting old messages loses facts such as \"I am a part-time employee in Chennai\", which still matter ten turns later.",
        "before": "8 messages, over the budget",
        "after": "\"The user is a part-time employee in the Chennai office…\" + the last 2 messages",
        "after_state": "masked",
        "internals": [
            ("When", "Triggered by Context Window Management (part 6) when the conversation is over budget."),
            ("Split", "Old messages vs recent ones. The recent part always starts with a user question."),
            ("Rolling summary", "The LLM writes 2-4 third-person sentences (\"The user...\"), merging the earlier summary, with one worked example and \"add no new facts\"."),
            ("Check it", "Output that looks like a transcript (User: / Assistant: lines) or is too long is rejected, and a safe extractive summary is used instead."),
            ("Compact the memory", "RemoveMessage(id=...) deletes the old messages from the checkpointed state. The PostgreSQL transcript is never touched."),
        ],
        "questions": [
            ("Why a rolling summary?", "Each summary builds on the last one, so cost stays flat however long the chat gets."),
            ("Why reject transcript-looking output?", "Measured: the small model once continued the chat and invented facts (\"annual vacation days, typically...\"). Invented facts are worse than none, because later turns would trust them."),
            ("What is lost?", "Small details. The transcript still has everything, and the user can ask again."),
        ],
        "limits": "Summaries can drop details. A number given early may need to be repeated.",
    },
    {
        "number": 10,
        "name": "Session Expiration Handling",
        "framework": "grey",
        "tech": "Redis TTL + PostgreSQL status + cron command",
        "file": "conversations/services/expiration.py",
        "summary": "Ends idle sessions and idle conversations safely, using two different clocks.",
        "problem": "Old sessions are risky on shared computers. Old AI memory wastes storage and can mix yesterday's context into today's question.",
        "before": "Alice writes in a conversation idle for 25 hours",
        "after": "410 \"This conversation ended after 24 hours…\"; history still readable",
        "after_state": "stopped",
        "internals": [
            ("Session clock: 30 minutes", "The Redis TTL is reset on every message. Redis deletes the key by itself when time runs out."),
            ("After a session expires", "A new session starts. Without a conversation ID, the next message starts a new conversation."),
            ("Conversation clock: 24 hours", "ensure_writable() checks last_activity_at before every new message."),
            ("Expired conversation", "Status becomes \"expired\", its LangGraph memory is deleted, new messages get 410, and reading still works."),
            ("Bulk clean-up", "python manage.py expire_conversations, run from cron, expires every idle conversation at once."),
        ],
        "questions": [
            ("Why two clocks?", "A session is \"this visit\". A conversation is \"this topic\", which the user may come back to later the same day."),
            ("Why 410 and not 404?", "The conversation exists and is still readable; it is only gone for writing. 410 Gone says exactly that."),
            ("Why delete the AI memory but keep the transcript?", "The memory is only needed to continue; the transcript is the user's record and the audit trail."),
        ],
        "limits": "After a session expires, a follow-up without a conversation ID starts a fresh conversation without context (see the demo). Clients can pass the conversation ID to continue.",
    },
]

PROBLEMS = [
    ("Follow-ups lose their meaning", "\"And for part-time staff?\"", "Retrieval searches for \"part-time staff\" with no topic and returns the wrong documents.", [8, 7]),
    ("People could read other people's chats", "Bob changes the ID in the URL to Alice's.", "A private HR conversation about pay or health is exposed.", [1, 5]),
    ("Messages could be lost or numbered twice", "The server crashes while answering; two tabs send at once.", "The question disappears, or the history is out of order.", [4, 3]),
    ("Long chats get slow and expensive", "Every turn resends the whole conversation.", "Costs grow every turn until the model's limit breaks.", [6, 9]),
    ("Old sessions never end", "A shared office computer, a chat from last week.", "Someone continues another person's session; old context leaks into new questions.", [2, 10]),
]

MEMORY_COMPARISON = [
    ("What it holds", "Every question and answer, in order", "A running summary + the newest messages"),
    ("Who reads it", "The user (history screen), admins, audits", "The AI, when answering the next question"),
    ("Size", "Grows with every message", "Stays within the token budget"),
    ("Trimmed?", "Never", "Yes: old messages folded into the summary"),
    ("Stored in", "PostgreSQL tables via the Django ORM", "PostgreSQL checkpoint tables via the LangGraph checkpointer"),
    ("Deleted when", "The user deletes the conversation", "The conversation expires or is deleted"),
]

RAG_JOURNEY = [
    ("You ask", "\"And for part-time staff?\"", False),
    ("Input validation & security", "Stage 3: safe, valid, private", False),
    ("Session & conversation", "Stage 4: who, which chat, what it means", True),
    ("Find documents", "Searches with the standalone question", False),
    ("AI writes the answer", "Within the token budget", False),
    ("You get the answer", "Saved to the transcript", False),
]

TURN_FLOW = [
    ("Session", "Find the Redis session, or start one", [2]),
    ("Which conversation", "Valid ID and owned by you, or 404", [1, 5]),
    ("Still open?", "Idle more than 24 h → 410", [10]),
    ("Lock and save the question", "One answer at a time; question saved as pending", [4]),
    ("Follow-up?", "Rules: continuation, very short, pronoun...", [8]),
    ("Rewrite", "LLM turns it into a standalone question", [7]),
    ("Fit the budget", "Over budget → summarise older messages", [6, 9]),
    ("Answer and save", "Next stage answers; answer + details saved; cache cleared", [4, 3]),
]

DESIGN = [
    ("Memory fails soft, security fails closed", "If the LLM is down, follow-ups are joined with the previous question and summaries become extractive, so the chat keeps working. Stage 3 security refuses instead."),
    ("Save the question first", "The question is committed before the AI runs, so a crash never loses it."),
    ("One answer at a time per conversation", "A Redis lock covers the whole AI step. Two tabs sending at once get 409 instead of mixing up the memory."),
    ("The client never picks the memory", "The LangGraph thread_id is the conversation ID, used only after the ownership check."),
    ("Two stores, two jobs", "Transcript for people (never trimmed); working memory for the AI (kept small)."),
    ("Log decisions, never text", "One log line per turn: IDs, follow-up yes or no, rewrite method, tokens, summarised, timing."),
]

PITCH = (
    "Stage 4 runs before retrieval and keeps track of who is chatting, which conversation they are in, and what "
    "their question means. Django REST Framework handles the API: conversation IDs are random UUIDs, validated and "
    "always looked up together with the owner, so another user's conversation returns 404. Each message is saved in "
    "PostgreSQL through the Django ORM before the AI runs, with row locks for numbering and a Redis lock so only one "
    "answer is written at a time. Redis also holds a 30-minute sliding session that points to the active "
    "conversation, and a cache of recent history. A LangGraph graph with a PostgreSQL checkpointer is the AI's "
    "working memory per conversation: rules detect follow-ups, an LLM rewrites them into standalone questions, and "
    "when the context goes over a token budget, older messages are folded into a rolling summary while the full "
    "transcript stays in PostgreSQL. Idle conversations become read-only after 24 hours. Memory features fail soft, "
    "and I measured them with a real model, fixing an echo bug and an invented-facts bug in the summaries."
)

QUESTIONS = [
    ("Why both the Django ORM and a LangGraph checkpointer? Isn't that duplicated?", "They do different jobs. The ORM tables are the permanent transcript for people. The checkpointer is the AI's compact working memory, which gets summarised and deleted on expiry."),
    ("What exactly is a LangGraph checkpointer?", "It saves a snapshot of the graph state after every step, keyed by thread_id. The next run with the same thread_id continues from the last snapshot, even on another server."),
    ("How does this scale to many servers?", "The servers keep no state: sessions, cache and locks are in Redis, and transcript and checkpoints are in PostgreSQL. Any server can handle any message."),
    ("What happens when the LLM is down?", "Nothing breaks. Follow-ups are joined with the previous question, and summaries become extractive."),
    ("How did you test it?", "Unit tests with a fake LLM, API tests against a real PostgreSQL test database, and a set of real-model cases that found and fixed three bugs."),
]

STATUSES = [
    ("201", "Message answered", "Normal turn: question and answer saved."),
    ("400", "Invalid input", "Malformed conversation_id or message in the body (part 1)."),
    ("404", "Not found", "Bad ID in the URL, missing, or someone else's: one identical answer (parts 1, 5)."),
    ("409", "Busy", "The previous message in this conversation is still being answered (part 4)."),
    ("410", "Gone", "The conversation expired after 24 idle hours; still readable (part 10)."),
    ("503", "Memory unavailable", "The AI step failed; the question was saved as failed (part 4)."),
]

FIXES = [
    ("\"Can I take them in half days?\" became \"Can I take half days off?\" (lost what \"them\" meant)", "Worked examples added to the prompt."),
    ("With the examples written inside the instructions, \"And for part-time staff?\" came back unchanged", "Examples sent as real chat turns; an echo of a clearly incomplete follow-up is rejected."),
    ("The summary continued the chat and invented facts", "Third-person format with an example; transcript-looking output is rejected and the extractive fallback used."),
    ("A standalone question with \"they\" was joined with the previous one", "Echoes are rejected only for clearly incomplete questions (strong signs)."),
    ("The model answered instead of rewriting", "A rewrite must still be a question."),
]
