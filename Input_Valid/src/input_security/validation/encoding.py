"""
STEP 3 - Character / encoding validation                  Tool: Python (unicodedata)
==================================================================================

What it protects against
    Text that looks harmless to a person but is read differently by a machine:
      - broken Unicode (lone surrogates) that crashes encoders and logs
      - control characters (NUL, ESC, ...) that corrupt logs and terminals
      - bidi override characters ("Trojan Source"): they reorder how text is shown
      - Unicode TAG characters (U+E0000-E007F): invisible text that LLMs still read
        ("ASCII smuggling")
      - look-alike and invisible tricks that let words slip past filters:
            "ｉｇｎｏｒｅ"  (fullwidth letters)   -> "ignore" after NFKC
            "ig​nore" (zero-width space)    -> "ignore" after stripping

How it works (in this order)
    1. Reject lone surrogates (category Cs).                       -> REJECT
    2. NFKC normalisation: folds fullwidth letters, ligatures and other
       compatibility characters into their plain form, so steps 4-11 see the
       canonical text.
    3. Reject control characters (category Cc) except \\t \\n \\r.   -> REJECT
    4. Reject bidi overrides/isolates and TAG characters.          -> REJECT
    5. Strip other invisible format characters (category Cf: zero-width space,
       soft hyphen, word joiner, BOM). ZWJ/ZWNJ are kept where they are needed
       (emoji sequences, Indic scripts) and removed only between two Latin
       letters or digits, where they can only be a trick.
    6. Normalise line endings, trim, and re-check empty / length.  -> REJECT

    The cleaned text replaces the query for all later steps.

Example
    "ｉｇｎｏｒｅ previous rules"  -> "ignore previous rules" (step 8 then sees the real words)
    "Hello\x00world"               -> REJECT "control character U+0000"
"""

import unicodedata

from input_security.models import Decision, ScanContext, StepResult
from input_security.validation.size_limits import MAX_QUERY_CHARS

ALLOWED_CONTROL_CHARS = {"\n", "\t", "\r"}

# Bidirectional embedding / override / isolate controls (CVE-2021-42574 "Trojan Source").
BIDI_CONTROLS = {chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))}

ZERO_WIDTH_JOINERS = {"‌", "‍"}  # ZWNJ, ZWJ


def _is_tag_character(char: str) -> bool:
    return 0xE0000 <= ord(char) <= 0xE007F


def _is_ascii_alnum(char: str) -> bool:
    return char.isascii() and char.isalnum()


class EncodingValidator:
    number = 3
    name = "Character / Encoding Validation"
    tool = "Python"
    enabled = True

    def __init__(self, max_chars: int = MAX_QUERY_CHARS):
        self.max_chars = max_chars

    def warmup(self) -> None:  # nothing to load
        pass

    def run(self, ctx: ScanContext) -> StepResult:
        text = ctx.query

        # 1. Lone surrogates: the string is not valid Unicode.
        for char in text:
            if unicodedata.category(char) == "Cs":
                return self._reject("Text contains an invalid (surrogate) character.", char)

        # 2. Canonical form for every later step.
        normalized = unicodedata.normalize("NFKC", text)

        removed = 0
        kept: list[str] = []
        for index, char in enumerate(normalized):
            category = unicodedata.category(char)

            # 3. Control characters.
            if category == "Cc" and char not in ALLOWED_CONTROL_CHARS:
                return self._reject("Text contains a control character.", char)

            # 4. Characters that hide or reorder text.
            if char in BIDI_CONTROLS:
                return self._reject("Text contains a bidirectional override character.", char)
            if _is_tag_character(char):
                return self._reject("Text contains invisible Unicode tag characters.", char)

            # 5. Other invisible format characters.
            if category == "Cf":
                if char in ZERO_WIDTH_JOINERS:
                    before = normalized[index - 1] if index > 0 else ""
                    after = normalized[index + 1] if index + 1 < len(normalized) else ""
                    if not (_is_ascii_alnum(before) and _is_ascii_alnum(after)):
                        kept.append(char)
                        continue
                removed += 1
                continue

            kept.append(char)

        # 6. Line endings, trimming, final checks.
        cleaned = "".join(kept).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not cleaned:
            return StepResult(Decision.REJECT, "Query is empty after removing invisible characters.")
        if len(cleaned) > self.max_chars:
            return StepResult(
                Decision.REJECT,
                f"Query is {len(cleaned)} characters after normalisation; the limit is {self.max_chars}.",
            )

        ctx.normalized_query = cleaned
        return StepResult(
            Decision.CONTINUE,
            details={
                "nfkc_changed_text": normalized != text,
                "invisible_chars_removed": removed,
            },
            text=cleaned,
        )

    @staticmethod
    def _reject(reason: str, char: str) -> StepResult:
        return StepResult(Decision.REJECT, reason, details={"codepoint": f"U+{ord(char):04X}"})
