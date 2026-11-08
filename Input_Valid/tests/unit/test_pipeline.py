"""Pipeline orchestration and the SECURITY DECISION, using fake steps."""

from input_security.decision import HTTP_STATUS, NEXT_STAGE
from input_security.models import Decision
from input_security.pipeline import SecurityPipeline, reject_oversized_body
from tests.conftest import FakeStep

QUERY = {"query": "How many annual leave days do employees get?"}


def test_all_pass_continues_to_authentication():
    result = SecurityPipeline([FakeStep(3), FakeStep(4)]).validate_payload(QUERY)
    assert result.decision == Decision.CONTINUE and result.allowed
    assert result.next_stage == NEXT_STAGE
    assert result.sanitized_query == QUERY["query"]
    assert [s.step for s in result.steps] == [1, 2, 3, 4]


def test_mask_carries_redacted_text_forward():
    redact = FakeStep(6, Decision.MASK, text="My email is <EMAIL_ADDRESS>")
    after = FakeStep(8)
    result = SecurityPipeline([redact, after]).validate_payload({"query": "My email is a@b.com"})
    assert result.decision == Decision.MASK and result.allowed
    assert result.sanitized_query == "My email is <EMAIL_ADDRESS>"
    assert after.calls == 1


def test_block_stops_the_pipeline_and_hides_the_query():
    later = FakeStep(10)
    result = SecurityPipeline([FakeStep(8, Decision.BLOCK, reason="Prompt injection detected."), later]).validate_payload(QUERY)
    assert result.decision == Decision.BLOCK and not result.allowed
    assert later.calls == 0
    assert result.sanitized_query is None
    # the reason is not shown to the end user
    assert "injection" not in result.message.lower()
    assert result.http_status == 403


def test_reject_shows_the_validation_reason():
    result = SecurityPipeline([FakeStep(3, Decision.REJECT, reason="Text contains a control character.")]).validate_payload(QUERY)
    assert result.decision == Decision.REJECT and result.message == "Text contains a control character."
    assert result.http_status == 422


def test_redirect_uses_the_nemo_message():
    step = FakeStep(11, Decision.REDIRECT, user_message="I can only help with HR policy questions.")
    result = SecurityPipeline([step]).validate_payload({"query": "Write me a poem"})
    assert result.decision == Decision.REDIRECT and not result.allowed
    assert result.message == "I can only help with HR policy questions."
    assert result.http_status == 200


def test_scanner_exception_fails_closed():
    later = FakeStep(10)
    result = SecurityPipeline([FakeStep(8, raises=RuntimeError("model crashed")), later]).validate_payload(QUERY)
    assert result.decision == Decision.ERROR and result.http_status == 503
    assert later.calls == 0
    assert result.steps[-1].reason == "Fake failed: RuntimeError"


def test_disabled_step_is_reported_as_skipped():
    disabled = FakeStep(7, enabled=False)
    result = SecurityPipeline([disabled]).validate_payload(QUERY)
    assert disabled.calls == 0
    assert result.steps[-1].skipped


def test_schema_errors_reject_before_any_scanner():
    step = FakeStep(3)
    result = SecurityPipeline([step]).validate_payload({"query": "   "})
    assert result.decision == Decision.REJECT and step.calls == 0
    assert result.errors[0]["type"] == "query_blank"


def test_public_dict_hides_steps_unless_exposed():
    result = SecurityPipeline([FakeStep(3)]).validate_payload(QUERY)
    assert "steps" not in result.public_dict(expose_steps=False)
    assert len(result.public_dict(expose_steps=True)["steps"]) == 3


def test_oversized_body():
    result = reject_oversized_body(50_000, 32_768)
    assert result.decision == Decision.REJECT and result.errors[0]["step"] == 2


def test_every_decision_has_an_http_status():
    assert set(HTTP_STATUS) == set(Decision)


class RecordingStep(FakeStep):
    """Records which text a step was given."""

    def __init__(self, number, attribute):
        super().__init__(number)
        self.attribute = attribute
        self.seen = None

    def run(self, ctx):
        self.seen = getattr(ctx, self.attribute)
        return super().run(ctx)


def test_local_detectors_see_unredacted_text_and_stage4_gets_redacted():
    from input_security.validation.encoding import EncodingValidator

    redact = FakeStep(6, Decision.MASK, text="My email is <EMAIL_ADDRESS>")
    injection = RecordingStep(8, "unredacted_query")   # what steps 7, 8, 9, 11 read
    guard = RecordingStep(10, "query")                  # what Llama Guard reads
    result = SecurityPipeline([EncodingValidator(), redact, injection, guard]).validate_payload(
        {"query": "My email is arun@company.com"}
    )
    assert injection.seen == "My email is arun@company.com"
    assert guard.seen == "My email is <EMAIL_ADDRESS>"
    assert result.sanitized_query == "My email is <EMAIL_ADDRESS>"
