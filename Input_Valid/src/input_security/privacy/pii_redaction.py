"""
STEP 6 - PII detection / redaction                       Tool: Microsoft Presidio
==============================================================================

What it protects against
    Personal data typed into the chat ("My Aadhaar is 2345 6789 0123 ...") would
    otherwise be stored in logs, sent to the embedding model, the vector search
    and the LLM. Presidio finds it and replaces it with a placeholder, and the
    request then continues (decision MASK).

How it works
    1. AnalyzerEngine finds PII in the text. It combines:
         - spaCy NER (named entities) for PERSON
         - pattern recognisers with checksums for EMAIL_ADDRESS, PHONE_NUMBER,
           CREDIT_CARD (Luhn), IBAN_CODE, IP_ADDRESS, US_SSN, IN_PAN, IN_AADHAAR
         - a custom PatternRecognizer for this company's EMPLOYEE_ID (EMP-123456)
       Each finding has a type, a position and a score; findings below
       PII_SCORE_THRESHOLD (0.4) are ignored. 0.4 is Presidio's score for a
       valid phone number with no word like "phone" next to it, so a higher
       threshold would let "+91 98765 43210" through.
    2. AnonymizerEngine replaces every finding with <ENTITY_TYPE>.
    3. The redacted text is what leaves this layer: it goes to Llama Guard
       (step 10, possibly another server) and to stage 4 and the RAG pipeline.
       Checks that run inside this process (steps 7, 8, 9, 11) read the text
       from before redaction (ScanContext.unredacted_query), because the
       placeholders make the step 8 model see injections that are not there.
    4. Only entity *types and counts* are reported, never the values.

Not redacted on purpose
    DATE_TIME and LOCATION: "Can I take leave on 25 December in Chennai?" needs
    both to be answered. Add them to PII_ENTITIES if your policy says otherwise.

spaCy model
    Production: en_core_web_lg (best PERSON accuracy, ~600 MB of RAM).
    Small machine: set PRESIDIO_SPACY_MODEL=en_core_web_sm in .env.
    Install with:  python -m spacy download en_core_web_sm

Example
    "My email is arun@company.com and my ID is EMP-104233. How many sick days do I get?"
    -> "My email is <EMAIL_ADDRESS> and my ID is <EMPLOYEE_ID>. How many sick days do I get?"
       decision MASK, entities {"EMAIL_ADDRESS": 1, "EMPLOYEE_ID": 1}
"""

from __future__ import annotations

import threading
from collections import Counter

from input_security.models import Decision, ScanContext, StepResult

PRESIDIO_LANGUAGE = "en"


class PresidioPiiRedactor:
    number = 6
    name = "PII Detection / Redaction"
    tool = "Microsoft Presidio"

    def __init__(
        self,
        spacy_model: str,
        entities: list[str],
        score_threshold: float = 0.4,
        employee_id_regex: str = r"\bEMP[-_]?\d{4,8}\b",
        enabled: bool = True,
    ):
        self.spacy_model = spacy_model
        self.entities = entities
        self.score_threshold = score_threshold
        self.employee_id_regex = employee_id_regex
        self.enabled = enabled
        self._analyzer = None
        self._anonymizer = None
        self._lock = threading.Lock()

    def _load(self):
        if self._analyzer is None:
            with self._lock:
                if self._analyzer is None:
                    import spacy.util
                    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
                    from presidio_analyzer.nlp_engine import NlpEngineProvider
                    from presidio_analyzer.predefined_recognizers import InAadhaarRecognizer
                    from presidio_anonymizer import AnonymizerEngine

                    # Presidio would otherwise try to download a missing model at runtime.
                    if not spacy.util.is_package(self.spacy_model):
                        raise RuntimeError(
                            f"spaCy model '{self.spacy_model}' is not installed. "
                            f"Run: python -m spacy download {self.spacy_model}"
                        )

                    nlp_engine = NlpEngineProvider(
                        nlp_configuration={
                            "nlp_engine_name": "spacy",
                            "models": [{"lang_code": PRESIDIO_LANGUAGE, "model_name": self.spacy_model}],
                        }
                    ).create_engine()
                    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=[PRESIDIO_LANGUAGE])
                    # This company's employee ids, e.g. EMP-104233.
                    analyzer.registry.add_recognizer(
                        PatternRecognizer(
                            supported_entity="EMPLOYEE_ID",
                            name="EmployeeIdRecognizer",
                            patterns=[Pattern("employee_id", self.employee_id_regex, 0.85)],
                            context=["employee", "emp", "staff", "id"],
                        )
                    )
                    # The built-in Aadhaar pattern only matches 12 digits written
                    # together. People usually type "4991 1866 5246", so add a pattern
                    # with optional spaces/dashes. The recogniser's Verhoeff checksum
                    # still has to pass, so random 12-digit numbers are not redacted.
                    analyzer.registry.add_recognizer(
                        InAadhaarRecognizer(
                            patterns=[Pattern("AADHAAR (grouped)", r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b", 0.5)]
                        )
                    )
                    self._anonymizer = AnonymizerEngine()
                    self._analyzer = analyzer
        return self._analyzer, self._anonymizer

    def warmup(self) -> None:
        self._load()

    def redact(self, text: str) -> tuple[str, dict[str, int]]:
        analyzer, anonymizer = self._load()
        findings = analyzer.analyze(
            text=text,
            language=PRESIDIO_LANGUAGE,
            entities=self.entities,
            score_threshold=self.score_threshold,
        )
        if not findings:
            return text, {}
        # When two recognisers flag the same span (an Aadhaar number also looks
        # like a phone number), the anonymizer keeps the higher-scoring one.
        # Count what was actually replaced, not every raw finding.
        result = anonymizer.anonymize(text=text, analyzer_results=findings)
        return result.text, dict(Counter(item.entity_type for item in result.items))

    def run(self, ctx: ScanContext) -> StepResult:
        redacted, counts = self.redact(ctx.query)
        if not counts:
            return StepResult(Decision.CONTINUE, "No PII found.")
        return StepResult(
            Decision.MASK,
            f"Redacted {sum(counts.values())} PII value(s).",
            details={"entities": counts},
            text=redacted,
        )
