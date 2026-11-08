"""
STEP 11 - Allowed topic / scope validation                 Tool: NeMo Guardrails
==============================================================================

What it does
    Keeps the assistant on its job. An HR policy assistant should not write
    poems, give stock tips or answer general-knowledge questions: off-topic use
    costs money, and answers outside the indexed documents are where the model
    makes things up. Off-topic questions get a friendly redirect, not an error.

How it works
    1. NeMo loads guardrails/topic_scope/ (config.yml + rails.co +
       allowed_topics.yml). The example questions are read from
       rails.config.custom_data.
    2. On first use the action embeds every example question with FastEmbed
       all-MiniLM-L6-v2 (NeMo's own default embedding model, ONNX, ~90 MB).
    3. NeMo runs the input rail "check topic scope" (rails.co):
           $in_scope = execute check_topic_scope
           if not $in_scope
             bot redirect to hr topics
             stop
    4. Python embeds the query and finds cosine similarities, then sends them
       to NeMo as context variables:
           allowed_similarity   = highest similarity to any allowed example
           off_topic_similarity = highest similarity to any off-topic example
       The action applies the rule (`decide_topic`). In scope when
           allowed_similarity >= TOPIC_MIN_SIMILARITY (0.35)
           and allowed_similarity >= off_topic_similarity
    5. Out of scope -> REDIRECT (HTTP 200, allowed=false) with the Colang message.

Why embeddings and not an LLM?
    About 5 ms on a CPU, no extra LLM call, and the same answer every time. For
    finer judgement, switch the rail to NeMo's LLM "self check input" (see the
    comment in guardrails/topic_scope/config.yml).

Example
    "Can I carry forward my unused leave?"  -> CONTINUE (topic leave_policy, 0.86)
    "Write me a poem about the ocean"       -> REDIRECT
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from input_security.settings import GUARDRAILS_DIR
from input_security.guardrails.runtime import check_input_rails, load_rails
from input_security.models import Decision, ScanContext, StepResult

CONFIG_DIR = GUARDRAILS_DIR / "topic_scope"


@dataclass(frozen=True)
class TopicScore:
    best_topic: str
    allowed_similarity: float
    off_topic_similarity: float


def decide_topic(score: TopicScore, min_similarity: float) -> bool:
    """The scope rule itself. Pure function, so it is easy to test."""
    return score.allowed_similarity >= min_similarity and score.allowed_similarity >= score.off_topic_similarity


class EmbeddingTopicIndex:
    """Example questions embedded once; queries are compared with cosine similarity."""

    def __init__(
        self,
        model_name: str,
        allowed_topics: dict[str, list[str]],
        off_topic_examples: list[str],
        cache_dir: Optional[str] = None,
    ):
        from nemoguardrails.embeddings.providers.fastembed import FastEmbedEmbeddingModel

        self._model = FastEmbedEmbeddingModel(model_name, **({"cache_dir": cache_dir} if cache_dir else {}))
        self._labels = [topic for topic, questions in allowed_topics.items() for _ in questions]
        allowed = [question for questions in allowed_topics.values() for question in questions]
        self._allowed = self._embed(allowed)
        self._off_topic = self._embed(off_topic_examples)

    def _embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.asarray(self._model.encode(texts), dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    def score(self, text: str) -> TopicScore:
        query = self._embed([text])[0]
        allowed = self._allowed @ query
        off_topic = self._off_topic @ query if len(self._off_topic) else np.array([0.0])
        best = int(np.argmax(allowed))
        return TopicScore(self._labels[best], round(float(allowed[best]), 4), round(float(off_topic.max()), 4))


class NemoTopicScope:
    number = 11
    name = "Allowed Topic / Scope Validation"
    tool = "NeMo Guardrails"

    def __init__(
        self,
        embedding_model: str,
        min_similarity: float,
        enabled: bool = True,
        timeout: float = 15,
        cache_dir: Optional[str] = None,
    ):
        self.embedding_model = embedding_model
        self.cache_dir = cache_dir
        self.min_similarity = min_similarity
        self.enabled = enabled
        self.timeout = timeout
        self._rails = None
        self._index: Optional[EmbeddingTopicIndex] = None
        self._lock = threading.Lock()

    # ---- NeMo action: called from the Colang flow ----------------------
    async def check_topic_scope(self, context: Optional[dict[str, Any]] = None) -> bool:
        context = context or {}
        score = TopicScore(
            best_topic=context.get("closest_topic", ""),
            allowed_similarity=float(context.get("allowed_similarity", 0.0)),
            off_topic_similarity=float(context.get("off_topic_similarity", 1.0)),
        )
        return decide_topic(score, self.min_similarity)

    def _load(self):
        if self._rails is None:
            with self._lock:
                if self._rails is None:
                    rails = load_rails(CONFIG_DIR, {"check_topic_scope": self.check_topic_scope}, self.timeout * 4)
                    data = rails.config.custom_data
                    self._index = EmbeddingTopicIndex(
                        self.embedding_model,
                        data["allowed_topics"],
                        data.get("off_topic_examples", []),
                        cache_dir=self.cache_dir,
                    )
                    self._rails = rails
        return self._rails

    def warmup(self) -> None:
        self._load()

    def run(self, ctx: ScanContext) -> StepResult:
        rails = self._load()
        score = self._index.score(ctx.unredacted_query)
        context = {
            "closest_topic": score.best_topic,
            "allowed_similarity": score.allowed_similarity,
            "off_topic_similarity": score.off_topic_similarity,
        }
        rails_result = check_input_rails(rails, ctx.unredacted_query, context, self.timeout)
        details = {**context, "min_similarity": self.min_similarity, "rail_status": rails_result.status.value}
        if rails_result.status.value == "blocked":
            details["rail"] = rails_result.rail
            return StepResult(Decision.REDIRECT, "Question is outside the allowed HR topics.", details, user_message=rails_result.content)
        return StepResult(Decision.CONTINUE, f"In scope (closest topic: {score.best_topic}).", details)
