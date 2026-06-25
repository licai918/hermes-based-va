"""Per-profile tool-dispatch HTTP API (ADR-0141).

The deterministic half of the per-profile Hermes surface the workbench BFF calls.
``POST /v1/tools:dispatch`` runs the same governed :func:`execute_tool` the channel
pipeline uses — no LLM — under one fixed profile, so structured resource reads and
writes stay deterministic. Bearer auth gates the route; the Profile Tool Allowlist
(ADR-0034/0035/0038) is enforced as a Tool Gate, so a tool outside the profile
comes back as a governed ``{"error": ...}`` (ADR-0020), never a raised exception.
Tool Gate denials and driver failures are HTTP 200 governed JSON; only auth and
request-shape problems are 4xx.

Like the gateway app this lives in the embedding venv and defaults mock-first
(ADR-0137): an unconfigured app dispatches against the MockDriver until the Toee
Business Datastore (ADR-0140) is wired behind the tools.
"""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from toee_hermes.execute import ToolDriver, execute_tool
from toee_hermes.plugin.profiles import allowlisted_tools
from toee_hermes.tool_gate import GateDecision, ToolExecutionContext, ToolGate

from .tool_backend import select_tool_driver

# Resource dispatch uses a Google-style custom method (AIP-136) so it never
# collides with a future resource-shaped REST path under /v1.
DISPATCH_PATH = "/v1/tools:dispatch"

_BEARER_PREFIX = "Bearer "


def profile_allowlist_gate(profile: str) -> ToolGate:
    """A Tool Gate that denies any tool outside ``profile``'s allowlist.

    Default-deny by allowlist (ADR-0034): the deployment fixes the profile, so a
    BFF that asks for a tool the profile does not own gets a governed
    ``policy_blocked`` denial rather than reaching a driver. This is the HTTP
    equivalent of the plugin's register-time non-registration (the agent path's
    enforcement), applied to the deterministic dispatch path.
    """
    allowed = allowlisted_tools(profile)

    def gate(request, context) -> GateDecision:  # noqa: ANN001 (ToolGate signature)
        if request.tool in allowed:
            return GateDecision(allow=True)
        return GateDecision(
            allow=False,
            error_class="policy_blocked",
            message=f'Tool "{request.tool}" is not in the "{profile}" allowlist.',
        )

    return gate


def create_tool_dispatch_app(
    *,
    api_token: str,
    profile: str,
    driver: Optional[ToolDriver] = None,
    gate: Optional[ToolGate] = None,
) -> FastAPI:
    """Build the per-profile tool-dispatch app from injected collaborators.

    ``profile`` fixes the home this server runs under (ADR-0139 separate homes);
    ``api_token`` is the bearer the BFF presents. Defaults are mock-first: an
    unconfigured app uses :func:`select_tool_driver` (``TOOL_BACKEND`` unset ->
    MockDriver, ADR-0137) and the profile allowlist gate, so it is safe to boot and
    contract-test before Postgres exists. Set ``TOOL_BACKEND=datastore`` to back the
    system-of-record tools with the Postgres driver (ADR-0140).
    """
    active_driver = driver if driver is not None else select_tool_driver()
    active_gate = gate or profile_allowlist_gate(profile)

    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        # Cheap liveness probe (ADR-0098): no token, driver, or datastore needed.
        return {"status": "ok"}

    @app.post(DISPATCH_PATH)
    async def dispatch(request: Request) -> Response:
        # Bearer auth, constant-time and fail-closed (mirrors the gateway's
        # internal-job secret, ADR-0106): a missing token config or a header
        # mismatch is 401 and the tool never runs.
        header = request.headers.get("authorization", "")
        token = header[len(_BEARER_PREFIX) :] if header.startswith(_BEARER_PREFIX) else ""
        if not api_token or not token or not hmac.compare_digest(token, api_token):
            return Response(status_code=401)

        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            body = {}

        tool = body.get("tool")
        action = body.get("action")
        params = body.get("params")
        # Shape errors are transport problems, not tool outcomes (ADR-0141): 400,
        # distinct from a governed tool error, which rides a 200 body.
        if not isinstance(tool, str) or not isinstance(action, str):
            return JSONResponse(
                status_code=400,
                content={"error": "tool and action are required strings"},
            )
        if params is not None and not isinstance(params, dict):
            return JSONResponse(
                status_code=400, content={"error": "params must be an object"}
            )

        # Actor attribution (ADR-0141): the BFF asserts the acting workbench account
        # in the request body. The server already trusts the BFF via the shared
        # bearer (the BFF is the only caller), so this asserted actor flows into the
        # context so governed writes — and the case_view read audit — attribute to
        # the real employee instead of NULL. Absent/blank stays fail-open (None).
        actor = body.get("actor_account_id")
        actor_account_id = actor if isinstance(actor, str) and actor else None

        result = execute_tool(
            tool=tool,
            action=action,
            params=params,
            context=ToolExecutionContext(profile=profile, user_id=actor_account_id),
            driver=active_driver,
            gate=active_gate,
        )

        if result.ok:
            return JSONResponse(content={"ok": True, "data": result.data})
        # Governed failure: never fabricate, never raise (ADR-0020). The class +
        # safe message ride a 200 so the BFF can render a governed error state.
        return JSONResponse(
            content={
                "ok": False,
                "error": {"class": result.error_class, "message": result.message},
            }
        )

    return app
