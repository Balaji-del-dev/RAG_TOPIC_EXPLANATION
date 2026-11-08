"""
STEP 7 - Enterprise sensitive data protection (DLP)      Tool: Microsoft Purview
==============================================================================

What it does
    Asks your organisation's Microsoft Purview Data Loss Prevention policies
    whether this text may be sent to the AI app. Presidio (step 6) finds generic
    PII. Purview applies *company* rules: confidential project names,
    sensitivity labels, custom sensitive info types, and so on.

    Use it only if your organisation has Purview DLP. It is off by default
    (PURVIEW_ENABLED=false). When it is ON and Purview cannot be reached, the
    request fails closed (ERROR, HTTP 503) and is never silently let through.

How it works
    1. Get an app-only token from Microsoft Entra ID with MSAL
       (client-credentials flow, scope https://graph.microsoft.com/.default).
       The app registration needs the Graph application permission
       Content.Process.All, granted by an admin.
    2. POST the text to Microsoft Graph v1.0:
           /users/{userId}/dataSecurityAndGovernance/processContent
       {userId} is the end user's Entra object id. Purview policies are scoped
       to users, so this step needs to know who is asking (see "Identity" below).
    3. Read the response:
           policyActions:   [{"@odata.type": "#microsoft.graph.restrictAccessAction",
                              "action": "restrictAccess", "restrictionAction": "block"}]
           processingErrors: [...]
         - any restrictionAction "block"  -> BLOCK  (APPLY DLP POLICY)
         - other actions (audit, warn)   -> CONTINUE, recorded in the trace
         - processingErrors              -> ERROR (fail closed)
         - empty policyActions           -> CONTINUE. Purview only returns actions
           when a DLP policy is scoped to this app.

What Purview sees
    The text *before* Presidio redaction (ctx.normalized_query). A DLP policy
    cannot judge "credit card numbers" if they were already replaced by
    <CREDIT_CARD>. Purview runs in your own Microsoft 365 tenant.

Identity
    The architecture puts authentication in stage 4, after this layer, so in
    production the API gateway must validate the JWT first and pass the user's
    `oid` claim on. The demo adapters read it from the X-User-Object-Id header.
    That header can be forged, so a real deployment must not trust it.

Not implemented (next step for a full integration)
    protectionScopes/compute: Purview's recommended first call, which tells the
    app which activities are in scope and returns an ETag to cache. Pass that
    ETag in If-None-Match. processContent then reports protectionScopeState
    "modified" when the scopes have changed.

Reference: https://learn.microsoft.com/graph/api/userdatasecurityandgovernance-processcontent
"""

from __future__ import annotations

import platform
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

from input_security.models import Decision, ScanContext, StepResult

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


def build_process_content_body(
    text: str,
    *,
    app_name: str,
    app_version: str,
    app_client_id: str,
    correlation_id: str,
    client_ip: Optional[str],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "contentToProcess": {
            "contentEntries": [
                {
                    "@odata.type": "microsoft.graph.processConversationMetadata",
                    "identifier": str(uuid.uuid4()),
                    "content": {"@odata.type": "microsoft.graph.textContent", "data": text},
                    "name": f"{app_name} user prompt",
                    "correlationId": correlation_id,
                    "sequenceNumber": 0,
                    "isTruncated": False,
                    "createdDateTime": now,
                    "modifiedDateTime": now,
                }
            ],
            "activityMetadata": {"activity": "uploadText"},
            "deviceMetadata": {
                "operatingSystemSpecifications": {
                    "operatingSystemPlatform": platform.system(),
                    "operatingSystemVersion": platform.release(),
                },
                "ipAddress": client_ip,
            },
            "protectedAppMetadata": {
                "name": app_name,
                "version": app_version,
                "applicationLocation": {
                    "@odata.type": "microsoft.graph.policyLocationApplication",
                    "value": app_client_id,
                },
            },
            "integratedAppMetadata": {"name": app_name, "version": app_version},
        }
    }


def interpret_process_content_response(data: dict[str, Any]) -> StepResult:
    """Turn Purview's answer into a step decision. Pure function, easy to test."""
    errors = data.get("processingErrors") or []
    actions = data.get("policyActions") or []
    details = {
        "policy_actions": [
            {"action": action.get("action"), "restriction": action.get("restrictionAction")} for action in actions
        ],
        "protection_scope_state": data.get("protectionScopeState"),
    }

    if errors:
        details["processing_errors"] = len(errors)
        return StepResult(Decision.ERROR, "Purview could not evaluate the content.", details)

    if any(str(action.get("restrictionAction", "")).lower() == "block" for action in actions):
        return StepResult(
            Decision.BLOCK,
            "A Microsoft Purview DLP policy blocks this content.",
            details,
            user_message="This message contains information that company policy does not allow "
            "you to share with the assistant.",
        )

    reason = "Purview policy actions recorded (no block)." if actions else "No Purview DLP policy matched."
    return StepResult(Decision.CONTINUE, reason, details)


class PurviewDlpCheck:
    number = 7
    name = "Enterprise Sensitive Data Protection"
    tool = "Microsoft Purview"

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        app_name: str,
        app_version: str,
        timeout: float = 5.0,
        enabled: bool = False,
        http_client: Optional[httpx.Client] = None,
        token_provider: Optional[Callable[[], str]] = None,
    ):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.app_name = app_name
        self.app_version = app_version
        self.timeout = timeout
        self.enabled = enabled
        self._http = http_client or httpx.Client(timeout=timeout)
        self._token_provider = token_provider
        self._msal_app = None
        self._lock = threading.Lock()

    def _access_token(self) -> str:
        if self._token_provider is not None:
            return self._token_provider()
        if not (self.tenant_id and self.client_id and self.client_secret):
            raise RuntimeError("Purview is enabled but PURVIEW_TENANT_ID / CLIENT_ID / CLIENT_SECRET are not set.")
        with self._lock:
            if self._msal_app is None:
                import msal

                self._msal_app = msal.ConfidentialClientApplication(
                    self.client_id,
                    authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                    client_credential=self.client_secret,
                )
        # MSAL keeps the token in memory and only calls Entra ID again when it expires.
        token = self._msal_app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in token:
            raise RuntimeError(f"Could not get a Graph token: {token.get('error')}")
        return token["access_token"]

    def warmup(self) -> None:
        self._access_token()

    def run(self, ctx: ScanContext) -> StepResult:
        if not ctx.user_id:
            return StepResult(
                Decision.ERROR,
                "Purview needs the signed-in user's Entra object id, and none was provided.",
            )

        body = build_process_content_body(
            ctx.unredacted_query,
            app_name=self.app_name,
            app_version=self.app_version,
            app_client_id=self.client_id,
            correlation_id=ctx.session_id or ctx.request_id,
            client_ip=ctx.client_ip,
        )
        response = self._http.post(
            f"{GRAPH_BASE_URL}/users/{ctx.user_id}/dataSecurityAndGovernance/processContent",
            json=body,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Client-Request-Id": ctx.request_id,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return interpret_process_content_response(response.json())
