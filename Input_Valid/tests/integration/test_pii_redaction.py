"""Step 6 with real Microsoft Presidio and a spaCy model."""

import pytest
import spacy.util

from input_security.models import Decision
from input_security.privacy.pii_redaction import PresidioPiiRedactor
from input_security.settings import get_settings
from tests.conftest import context

SETTINGS = get_settings()
MODEL = SETTINGS.presidio_spacy_model
pytestmark = pytest.mark.skipif(not spacy.util.is_package(MODEL), reason=f"python -m spacy download {MODEL}")


@pytest.fixture(scope="module")
def redactor():
    return PresidioPiiRedactor(MODEL, SETTINGS.pii_entities, SETTINGS.pii_score_threshold, SETTINGS.employee_id_regex)


def test_email_and_employee_id(redactor):
    result = redactor.run(context("My email is arun@company.com and my ID is EMP-104233. How many sick days do I get?"))
    assert result.decision == Decision.MASK
    assert result.text == "My email is <EMAIL_ADDRESS> and my ID is <EMPLOYEE_ID>. How many sick days do I get?"
    assert result.details["entities"] == {"EMAIL_ADDRESS": 1, "EMPLOYEE_ID": 1}


def test_indian_identifiers_and_phone(redactor):
    text, counts = redactor.redact("Call me on +91 98765 43210. PAN ABCPE1234F, Aadhaar 4991 1866 5246.")
    assert "<PHONE_NUMBER>" in text and "<IN_PAN>" in text and "<IN_AADHAAR>" in text
    assert counts["PHONE_NUMBER"] == 1  # the Aadhaar number is not double-counted as a phone


def test_credit_card(redactor):
    text, _ = redactor.redact("Card 4111 1111 1111 1111 was charged, can HR reimburse it?")
    assert text == "Card <CREDIT_CARD> was charged, can HR reimburse it?"


@pytest.mark.parametrize(
    "text",
    [
        "How many annual leave days do employees get?",
        "Can I take leave on 25 December in Chennai?",
        "I joined in 2019 and have 12 years of experience, how many leave days?",
        "What is the notice period for employees with 3 to 5 years of service?",
        "Random number 1234 5678 9012 in my query",  # fails the Aadhaar checksum
    ],
)
def test_no_false_positives(redactor, text):
    assert redactor.run(context(text)).decision == Decision.CONTINUE
