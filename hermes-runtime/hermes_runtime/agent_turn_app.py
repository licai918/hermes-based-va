"""``POST /v1/agent:turn`` — the per-profile agent-turn route (ADR-0147 Slice 1).

A second, distinct route added beside ``tools:dispatch`` on the *same* per-profile
server (Fork A1): one process, one bearer, one port (ADR-0141 "two capabilities
behind one deployment"). It keeps the deterministic dispatch app LLM-free —
generation lives here, not in :mod:`hermes_runtime.tool_dispatch_app` — while
reusing that app's bearer auth and ``actor_account_id`` convention verbatim.

AIP-136 custom method, like ``tools:dispatch``. The turn is synchronous (Fork B1)
and runs the unbound ``internal_copilot`` seam
(:func:`hermes_runtime.copilot_turn.make_copilot_run_turn`), so it is structurally
no-send (ADR-0035/0067). The ``channel`` selects the turn mode: the three draft
channels (sms/email/internal_note) return a per-channel draft envelope and record a
``draft_generated`` audit; ``chat`` (Slice 4, #39) returns a ``{reply, provenance}``
conversational reply and records no audit (parity with the in-memory handleChat).
Auth and request-shape problems are 4xx (parity with ``tool_dispatch_app``); a
governed turn failure would ride a 200 ``{ok: false}``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from toee_hermes.plugin.profiles import INTERNAL

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.tool_dispatch_app import bearer_authorized

# AIP-136 custom method, sibling to DISPATCH_PATH; never collides with a future
# resource-shaped REST path under /v1.
AGENT_TURN_PATH = "/v1/agent:turn"

# The turn modes the BFF selects (ADR-0147). The three draft channels (sms/email/
# internal_note, Slice 2) each return a per-channel draft envelope and record a
# draft_generated audit. `chat` (Slice 4, #39) is a conversational reply mode: it
# returns a `{reply, provenance}` envelope and records NO audit — parity with the
# in-memory handleChat, which writes none (a chat reply is not a formal draft).
VALID_CHANNELS = frozenset({"sms", "email", "internal_note", "chat"})

# run_turn(*, channel, case_id, prompt) -> {"draft", "model", "profile"}. The one
# model boundary: tests inject a deterministic callable; production defaults to the
# scripted/stub copilot turn (Slice 1) and the real OpenRouter turn (Slice 3).
RunTurn = Callable[..., dict[str, Any]]


def _record_draft_generated(
    driver: Any, *, case_id: str, channel: str, actor: Optional[str]
) -> None:
    """Record the ``draft_generated`` audit server-side (ADR-0147 #47, option i).

    Reuses the existing datastore audit writer (``PostgresDriver.record_audit`` →
    ``insert_audit``) — the same path the case-mutation cutover uses — so the row
    lands in the Postgres ``workbench_audit_log`` the governed audit-log read
    (``toee_workbench_read.get_audit_log``) now consults, retiring the BFF's
    write-only-in-API-mode audit. ``detail`` mirrors the BFF semantics byte-for-byte:
    the channel ACTION (``draft_sms``/``draft_email``/``draft_internal_note``), not the
    bare channel. A driver without ``record_audit`` (the MockDriver, or no driver in
    the route-only tests) is a no-op sink — mock mode persists no audit, exactly like
    every other API-path governed write in mock mode (no crash).
    """
    recorder = getattr(driver, "record_audit", None)
    if recorder is None:
        return
    recorder(
        profile=INTERNAL,
        account_id=actor,
        action="draft_generated",
        target_type="case",
        target_id=case_id,
        details={"detail": f"draft_{channel}"},
    )


def add_agent_turn_route(
    app: FastAPI,
    *,
    api_token: str,
    run_turn: Optional[RunTurn] = None,
    driver: Any = None,
) -> FastAPI:
    """Mount the synchronous ``agent:turn`` draft route onto ``app`` (ADR-0147).

    ``api_token`` is the same per-process bearer the dispatch route uses.
    ``run_turn`` defaults to the unbound ``internal_copilot`` scripted/stub seam; it
    boots lazily (per request), so mounting the route never loads the agent.
    ``driver`` is the ``TOOL_BACKEND``-selected tool driver (ADR-0140) the route
    records the ``draft_generated`` audit through (option i, #47); when it is the
    MockDriver (or ``None``), the audit write is a no-op sink, so a mock-first server
    still drafts without persisting an audit.
    """
    runner = run_turn if run_turn is not None else make_copilot_run_turn()

    @app.post(AGENT_TURN_PATH)
    async def agent_turn(request: Request) -> Response:
        # Same bearer as tools:dispatch, fail-closed (ADR-0106/0141): a missing
        # token config or a header mismatch is 401 and the turn never runs.
        if not bearer_authorized(request, api_token):
            return Response(status_code=401)

        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            body = {}

        channel = body.get("channel")
        case_id = body.get("case_id")
        # Shape errors are transport problems, not turn outcomes (parity with
        # tool_dispatch_app): 4xx, distinct from a governed turn failure on a 200.
        if not isinstance(channel, str) or channel not in VALID_CHANNELS:
            return JSONResponse(
                status_code=400,
                content={"error": "channel must be one of sms, email, internal_note, chat"},
            )
        if not isinstance(case_id, str) or not case_id:
            return JSONResponse(
                status_code=400, content={"error": "case_id is required"}
            )

        prompt = body.get("prompt")
        prompt = prompt if isinstance(prompt, str) and prompt else None

        # actor_account_id rides the body like dispatch (ADR-0141 actor attribution);
        # the BFF asserts the acting employee under the shared bearer. Absent/blank
        # stays fail-open (None), mirroring tool_dispatch_app.
        actor = body.get("actor_account_id")
        actor_account_id = actor if isinstance(actor, str) and actor else None

        result = runner(channel=channel, case_id=case_id, prompt=prompt)

        # The text is the agent's final_response (Fork E1); provenance records the
        # model boundary + the (structurally no-send) profile that produced it.
        # The per-channel envelope mirrors the in-process toee_copilot_draft tool
        # output byte-for-byte (ADR-0147 Slice 2) so the BFF body has store-path
        # parity: sms/email key on `channel`, email adds `subject`, internal_note
        # keys on `kind` (no channel). `chat` (Slice 4) keys on `reply` instead — a
        # conversational reply, not a draft.
        if channel == "chat":
            data: dict[str, Any] = {"reply": result["draft"]}
        elif channel == "internal_note":
            data = {"kind": "internal_note", "draft": result["draft"]}
        elif channel == "email":
            data = {
                "channel": "email",
                "subject": result["subject"],
                "draft": result["draft"],
            }
        else:  # sms
            data = {"channel": "sms", "draft": result["draft"]}
        data["provenance"] = {"model": result["model"], "profile": result["profile"]}

        # Option (i), #47: record draft_generated server-side on SUCCESS only, in the
        # governed datastore audit (no row on a 4xx shape error above, and none if the
        # turn raised before here). Mock mode is a no-op sink. `chat` is EXCLUDED: a
        # conversational reply is not a draft, so it records no audit — parity with the
        # in-memory handleChat, which writes none (Slice 4, #39).
        if channel != "chat":
            _record_draft_generated(
                driver, case_id=case_id, channel=channel, actor=actor_account_id
            )
        return JSONResponse(content={"ok": True, "data": data})

    return app
