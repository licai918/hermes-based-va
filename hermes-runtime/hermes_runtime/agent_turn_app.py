"""``POST /v1/agent:turn`` — the per-profile agent-turn route (ADR-0147 Slice 1).

A second, distinct route added beside ``tools:dispatch`` on the *same* per-profile
server (Fork A1): one process, one bearer, one port (ADR-0141 "two capabilities
behind one deployment"). It keeps the deterministic dispatch app LLM-free —
generation lives here, not in :mod:`hermes_runtime.tool_dispatch_app` — while
reusing that app's bearer auth and ``actor_account_id`` convention verbatim.

AIP-136 custom method, like ``tools:dispatch``. The turn is synchronous (Fork B1)
and runs the unbound ``internal_copilot`` draft seam
(:func:`hermes_runtime.copilot_turn.make_copilot_run_turn`), so it is structurally
no-send (ADR-0035/0067). Auth and request-shape problems are 4xx (parity with
``tool_dispatch_app``); a governed turn failure would ride a 200 ``{ok: false}``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.tool_dispatch_app import bearer_authorized

# AIP-136 custom method, sibling to DISPATCH_PATH; never collides with a future
# resource-shaped REST path under /v1.
AGENT_TURN_PATH = "/v1/agent:turn"

# The draft channels the BFF selects (ADR-0147). All three are wired end-to-end as
# of Slice 2 (sms/email/internal_note), each with its own per-channel envelope.
VALID_CHANNELS = frozenset({"sms", "email", "internal_note"})

# run_turn(*, channel, case_id, prompt) -> {"draft", "model", "profile"}. The one
# model boundary: tests inject a deterministic callable; production defaults to the
# scripted/stub copilot turn (Slice 1) and the real OpenRouter turn (Slice 3).
RunTurn = Callable[..., dict[str, Any]]


def add_agent_turn_route(
    app: FastAPI, *, api_token: str, run_turn: Optional[RunTurn] = None
) -> FastAPI:
    """Mount the synchronous ``agent:turn`` draft route onto ``app`` (ADR-0147).

    ``api_token`` is the same per-process bearer the dispatch route uses.
    ``run_turn`` defaults to the unbound ``internal_copilot`` scripted/stub seam; it
    boots lazily (per request), so mounting the route never loads the agent.
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
                content={"error": "channel must be one of sms, email, internal_note"},
            )
        if not isinstance(case_id, str) or not case_id:
            return JSONResponse(
                status_code=400, content={"error": "case_id is required"}
            )

        prompt = body.get("prompt")
        prompt = prompt if isinstance(prompt, str) and prompt else None

        # actor_account_id rides the body like dispatch (ADR-0141 actor attribution);
        # the BFF asserts the acting employee under the shared bearer. Slice 1 keeps
        # the draft_generated audit on the BFF (ADR-0147 sub-fork), so the actor is
        # accepted for forward-compat and not yet threaded into a server-side audit.
        result = runner(channel=channel, case_id=case_id, prompt=prompt)

        # The draft is the agent's final_response (Fork E1); provenance records the
        # model boundary + the (structurally no-send) profile that produced it.
        # The per-channel envelope mirrors the in-process toee_copilot_draft tool
        # output byte-for-byte (ADR-0147 Slice 2) so the BFF body has store-path
        # parity: sms/email key on `channel`, email adds `subject`, internal_note
        # keys on `kind` (no channel).
        if channel == "internal_note":
            data: dict[str, Any] = {"kind": "internal_note", "draft": result["draft"]}
        elif channel == "email":
            data = {
                "channel": "email",
                "subject": result["subject"],
                "draft": result["draft"],
            }
        else:  # sms
            data = {"channel": "sms", "draft": result["draft"]}
        data["provenance"] = {"model": result["model"], "profile": result["profile"]}
        return JSONResponse(content={"ok": True, "data": data})

    return app
