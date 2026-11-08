"""Settings for the conversation memory graph."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MemorySettings:
    # 6: tokens allowed for summary + recent messages + the question, handed to the answer step.
    max_context_tokens: int = 1200
    # 9: messages kept word for word when older ones are summarised (6 = the last 3 turns).
    keep_recent_messages: int = 6
