"""
STEP 4 - Language detection                                       Tool: fastText
==============================================================================

What it does
    Finds out which language the query is written in, so step 5 can apply the
    language policy. This step only *detects*; it never rejects anything.

How it works
    1. Load Facebook's language-identification model `lid.176.ftz` once
       (176 languages, under 1 MB, about 1 ms per query on a CPU).
       Download it with:  python scripts/download_models.py --only fasttext
    2. Count the letters. Under LANGUAGE_MIN_LETTERS (default 12) the text is too
       short for a reliable answer ("ok?", "PTO?"), so the result is marked
       reliable=False and step 5 lets it through.
    3. fastText needs one line of text, so newlines are joined with spaces.
    4. `model.predict(text, k=3)` returns the 3 most likely languages:
           (('__label__en', '__label__es', ...), (0.95, 0.004, ...))
       The "__label__" prefix is removed, leaving ISO codes such as "en", "ta", "fr".
    5. The result is stored on the context (ctx.language) for step 5.

Package note
    `fasttext-predict` is the official fastText C++ code built for prediction
    only. It has wheels for Python 3.12 and needs no compiler. It is imported
    as `fasttext`, like the full package.

Example
    "How many annual leave days do employees get?" -> en, 0.95
    "Combien de jours de congé ai-je par an ?"      -> fr, 0.99
    "எனக்கு எத்தனை விடுப்பு நாட்கள் உள்ளன?"            -> ta, 0.998
"""

import threading
from dataclasses import dataclass, field
from pathlib import Path

from input_security.models import Decision, ScanContext, StepResult


@dataclass(frozen=True)
class LanguageResult:
    language: str  # ISO 639 code, or "und" when undetermined
    confidence: float
    candidates: list[tuple[str, float]] = field(default_factory=list)
    reliable: bool = True


class FastTextLanguageDetector:
    number = 4
    name = "Language Detection"
    tool = "fastText"

    def __init__(self, model_path: Path, min_letters: int = 12, enabled: bool = True, top_k: int = 3):
        self.model_path = Path(model_path)
        self.min_letters = min_letters
        self.enabled = enabled
        self.top_k = top_k
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    if not self.model_path.exists():
                        raise FileNotFoundError(
                            f"fastText model not found at {self.model_path}. "
                            "Run: python scripts/download_models.py --only fasttext"
                        )
                    import fasttext

                    self._model = fasttext.load_model(str(self.model_path))
        return self._model

    def warmup(self) -> None:
        self._load()

    def detect(self, text: str) -> LanguageResult:
        letters = sum(char.isalpha() for char in text)
        if letters < self.min_letters:
            return LanguageResult("und", 0.0, [], reliable=False)

        one_line = " ".join(text.split())
        labels, scores = self._load().predict(one_line, k=self.top_k)
        candidates = [
            (label.replace("__label__", ""), round(float(score), 4)) for label, score in zip(labels, scores)
        ]
        best_language, best_score = candidates[0]
        return LanguageResult(best_language, best_score, candidates, reliable=True)

    def run(self, ctx: ScanContext) -> StepResult:
        result = self.detect(ctx.query)
        ctx.language = result
        return StepResult(
            Decision.CONTINUE,
            details={
                "language": result.language,
                "confidence": result.confidence,
                "candidates": result.candidates,
                "reliable": result.reliable,
            },
        )
