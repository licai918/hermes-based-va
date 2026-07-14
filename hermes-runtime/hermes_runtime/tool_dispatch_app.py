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
import logging
from typing import Any, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from toee_hermes.execute import ToolDriver, execute_tool
from toee_hermes.plugin.profiles import allowlisted_tools
from toee_hermes.tool_gate import GateDecision, ToolExecutionContext, ToolGate

from .tool_backend import memory_enabled, select_tool_driver

logger = logging.getLogger(__name__)

# Resource dispatch uses a Google-style custom method (AIP-136) so it never
# collides with a future resource-shaped REST path under /v1.
DISPATCH_PATH = "/v1/tools:dispatch"

_BEARER_PREFIX = "Bearer "

# The only tool whose dispatch-time identity is resolved from a case (S16,
# PAC-4): a Workbench correction/clear must bind to the SAME key the customer's
# own next turn reads, not the internal_copilot param carve-out's dead
# provisional:{channel_identity_id} key. Every other tool keeps identity=None,
# as before (minimal blast radius).
_CASE_IDENTITY_TOOL = "toee_customer_memory"


def bearer_authorized(request: Request, api_token: str) -> bool:
    """Constant-time, fail-closed bearer check shared by the per-profile routes.

    A missing token config, a missing/garbled header, or a mismatch is unauthorized
    (mirrors the gateway's internal-job secret, ADR-0106). Extracted so the
    deterministic ``tools:dispatch`` route and the ``agent:turn`` route (ADR-0147)
    enforce the *same* auth from one source of truth.
    """
    header = request.headers.get("authorization", "")
    token = header[len(_BEARER_PREFIX) :] if header.startswith(_BEARER_PREFIX) else ""
    return bool(api_token) and bool(token) and hmac.compare_digest(token, api_token)


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


def _gateway_store() -> Any:
    """Build the Postgres gateway store for dispatch-time case identity lookups (S16).

    Deferred import keeps ``psycopg`` out of a mock deployment's import path (same
    reasoning as ``select_tool_driver``'s ``PostgresDriver`` branch; mirrors
    ``openrouter.py``'s own ``_gateway_store``); only reached under
    :func:`memory_enabled`, so a mock/unset deployment never constructs it.
    """
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    return PostgresGatewayStore()


def _resolve_case_identity(
    tool: str, params: Optional[dict[str, Any]], store: Optional[Any]
) -> Optional[dict[str, Any]]:
    """Case-bound identity for a Workbench correction write (S16, PAC-4).

    A Workbench employee's ``toee_customer_memory`` write must bind to the SAME
    key the customer's own next turn reads (``binding_key_from_identity``), not
    the ``internal_copilot`` param carve-out's dead ``provisional:{id}`` key
    (S02). Resolves the case's thread identity -- verified or provisional, the
    same shape S07/S08 use -- via ``PostgresGatewayStore.load_case_identity``
    (S08), keyed off ``case_id`` riding in ``params`` (the BFF passes it,
    mirroring existing case writes). Scoped to :data:`_CASE_IDENTITY_TOOL` only;
    every other tool keeps ``identity=None`` as before.

    Gated by :func:`memory_enabled` and fail-closed like every other Customer
    Memory read in this codebase (S07/S08): disabled, a missing/non-string
    ``case_id``, an unknown/threadless case, or a store error all resolve to
    ``None`` and never raise -- the write falls back to today's
    param-carve-out/``policy_blocked`` path rather than a 500 (ADR-0020).
    """
    if tool != _CASE_IDENTITY_TOOL or not memory_enabled():
        return None
    case_id = (params or {}).get("case_id")
    if not (isinstance(case_id, str) and case_id):
        return None
    resolved_store = store if store is not None else _gateway_store()
    try:
        return resolved_store.load_case_identity(case_id)
    except Exception as exc:
        # ponytail: swallow so a store hiccup degrades to "no identity bound" (the
        # pre-existing param-carve-out/policy_blocked path), never a 500 -- same
        # philosophy as openrouter.py's _load_turn_memory swallow. Case id +
        # exception TYPE only -- never str(exc), which could echo store content.
        logger.warning(
            "Case identity lookup failed case_id=%s error_type=%s; dispatch "
            "continues with no identity bound",
            case_id,
            type(exc).__name__,
        )
        return None


def create_tool_dispatch_app(
    *,
    api_token: str,
    profile: str,
    driver: Optional[ToolDriver] = None,
    gate: Optional[ToolGate] = None,
    store: Optional[Any] = None,
) -> FastAPI:
    """Build the per-profile tool-dispatch app from injected collaborators.

    ``profile`` fixes the home this server runs under (ADR-0139 separate homes);
    ``api_token`` is the bearer the BFF presents. Defaults are mock-first: an
    unconfigured app uses :func:`select_tool_driver` (``TOOL_BACKEND`` unset ->
    MockDriver, ADR-0137) and the profile allowlist gate, so it is safe to boot and
    contract-test before Postgres exists. Set ``TOOL_BACKEND=datastore`` to back the
    system-of-record tools with the Postgres driver (ADR-0140). ``store`` injects the
    gateway store :func:`_resolve_case_identity` uses to resolve a case's identity
    (S16, PAC-4) -- tests only; production always resolves it lazily per dispatch
    (mirrors ``make_copilot_run_turn``/``make_openrouter_run_turn``'s ``store`` seam).
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
        # Bearer auth, constant-time and fail-closed (ADR-0106): a missing token
        # config or a header mismatch is 401 and the tool never runs.
        if not bearer_authorized(request, api_token):
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

        # S16/PAC-4: for toee_customer_memory with a case_id, bind the write to the
        # case's resolved identity so it round-trips to the customer's own read key
        # (see _resolve_case_identity). Every other tool keeps identity=None.
        identity = _resolve_case_identity(tool, params, store)

        result = execute_tool(
            tool=tool,
            action=action,
            params=params,
            context=ToolExecutionContext(
                profile=profile, user_id=actor_account_id, identity=identity
            ),
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
