"""Step 7: Microsoft Purview, with the Graph API mocked (no tenant needed)."""

import json

import httpx

from input_security.models import Decision
from input_security.privacy.purview_dlp import PurviewDlpCheck, interpret_process_content_response
from tests.conftest import context

BLOCK_RESPONSE = {
    "protectionScopeState": "notModified",
    "policyActions": [
        {"@odata.type": "#microsoft.graph.restrictAccessAction", "action": "restrictAccess", "restrictionAction": "block"}
    ],
    "processingErrors": [],
}


def make_check(handler):
    return PurviewDlpCheck(
        tenant_id="t", client_id="app-id", client_secret="s", app_name="HR Policy Assistant",
        app_version="1.0", enabled=True, http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        token_provider=lambda: "test-token",
    )


def test_block_action_blocks():
    assert interpret_process_content_response(BLOCK_RESPONSE).decision == Decision.BLOCK


def test_no_policy_continues():
    result = interpret_process_content_response({"policyActions": [], "processingErrors": []})
    assert result.decision == Decision.CONTINUE


def test_audit_only_continues_and_is_recorded():
    data = {"policyActions": [{"action": "restrictAccess", "restrictionAction": "audit"}], "processingErrors": []}
    result = interpret_process_content_response(data)
    assert result.decision == Decision.CONTINUE
    assert result.details["policy_actions"] == [{"action": "restrictAccess", "restriction": "audit"}]


def test_processing_errors_fail_closed():
    result = interpret_process_content_response({"policyActions": [], "processingErrors": [{"message": "x"}]})
    assert result.decision == Decision.ERROR


def test_request_shape_sent_to_graph():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=BLOCK_RESPONSE)

    ctx = context("Card 4111 1111 1111 1111")
    ctx.normalized_query = ctx.query
    ctx.user_id = "5def8f26-aff8-4db6-a08c-0fcf8f1aa2ba"
    result = make_check(handler).run(ctx)

    assert result.decision == Decision.BLOCK
    assert seen["url"] == ("https://graph.microsoft.com/v1.0/users/5def8f26-aff8-4db6-a08c-0fcf8f1aa2ba"
                           "/dataSecurityAndGovernance/processContent")
    assert seen["auth"] == "Bearer test-token"
    entry = seen["body"]["contentToProcess"]["contentEntries"][0]
    assert entry["@odata.type"] == "microsoft.graph.processConversationMetadata"
    assert entry["content"] == {"@odata.type": "microsoft.graph.textContent", "data": "Card 4111 1111 1111 1111"}
    assert seen["body"]["contentToProcess"]["activityMetadata"] == {"activity": "uploadText"}
    assert seen["body"]["contentToProcess"]["protectedAppMetadata"]["applicationLocation"]["value"] == "app-id"


def test_missing_user_id_fails_closed():
    result = make_check(lambda request: httpx.Response(200, json={})).run(context("hello there"))
    assert result.decision == Decision.ERROR


def test_http_error_raises_so_pipeline_fails_closed():
    check = make_check(lambda request: httpx.Response(503))
    ctx = context("hello")
    ctx.user_id = "u"
    try:
        check.run(ctx)
    except httpx.HTTPStatusError:
        return
    raise AssertionError("expected HTTPStatusError")
