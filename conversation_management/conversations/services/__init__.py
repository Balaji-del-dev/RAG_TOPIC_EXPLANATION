"""
Django side of session & conversation management, one module per responsibility:

    conversation_ids.py  1   Conversation ID Validation
    user_sessions.py     2   User Session Retrieval            (Redis)
    history.py           3   Conversation History Retrieval    (PostgreSQL + Redis cache)
                         4   Chat History Persistence          (PostgreSQL)
    ownership.py         5   Conversation Ownership Validation
    expiration.py        10  Session Expiration Handling       (Redis TTL + PostgreSQL)
    memory.py                connects Django to the LangGraph memory (steps 6-9)
    chat_turn.py             runs one chat turn through all of the above
"""
