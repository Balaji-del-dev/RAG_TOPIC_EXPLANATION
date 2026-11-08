"""
SECURITY DECISION - turns the step results into one final answer.

    Invalid request ------> REJECT    HTTP 422   steps 1-3 and 5
    Prompt attack --------> BLOCK     HTTP 403   steps 8-9
    PII ------------------> MASK      HTTP 200   step 6, continues with the redacted text
    Confidential data ----> BLOCK     HTTP 403   step 7, Purview DLP policy
    Harmful content ------> BLOCK     HTTP 403   step 10
    Unsupported topic ----> REDIRECT  HTTP 200   step 11, allowed=false + redirect message
    Safe input -----------> CONTINUE  HTTP 200   -> stage 4: AUTHENTICATION & AUTHORIZATION
    Scanner failure ------> ERROR     HTTP 503   fail closed: never skip a broken check

What the end user is told
    REJECT  : the validation reason ("Query cannot be empty"), which is safe to show.
    BLOCK   : a generic message. Saying *which* scanner fired helps an attacker
              tune the next attempt. The detail goes to the server log only.
    REDIRECT: the message written in the NeMo Colang flow.
"""

from __future__ import annotations

from typing import Iterable, Optional

from input_security.models import STOP_DECISIONS, Decision, StepReport, StepResult

NEXT_STAGE = "AUTHENTICATION_AND_AUTHORIZATION"

HTTP_STATUS = {
    Decision.CONTINUE: 200,
    Decision.MASK: 200,
    Decision.REDIRECT: 200,
    Decision.REJECT: 422,
    Decision.BLOCK: 403,
    Decision.ERROR: 503,
}

DEFAULT_MESSAGES = {
    Decision.CONTINUE: "Query passed input validation.",
    Decision.MASK: "Query passed input validation. Personal data was masked before processing.",
    Decision.REDIRECT: "This question is outside what the assistant can help with.",
    Decision.REJECT: "The request is not valid.",
    Decision.BLOCK: "This request cannot be processed because it breaks the assistant's usage policy.",
    Decision.ERROR: "Input validation is temporarily unavailable. Please try again shortly.",
}


def final_decision(reports: Iterable[StepReport]) -> Decision:
    reports = list(reports)
    for report in reports:
        if report.decision in STOP_DECISIONS:
            return report.decision
    if any(report.decision == Decision.MASK for report in reports):
        return Decision.MASK
    return Decision.CONTINUE


def message_for(decision: Decision, deciding: Optional[StepResult]) -> str:
    if deciding is not None and deciding.user_message:
        return deciding.user_message
    if decision == Decision.REJECT and deciding is not None and deciding.reason:
        return deciding.reason
    return DEFAULT_MESSAGES[decision]


def is_allowed(decision: Decision) -> bool:
    return decision in (Decision.CONTINUE, Decision.MASK)
