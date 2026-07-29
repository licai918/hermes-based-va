"""0.0.5 S27 (FR-33, D3): L7's ``feedback_derived`` provenance, framework-derived.

The twin of ``test_feedback_derived_source.py``. D3 assigned S01 two things for
L7: the third enum value, and a provenance resolver derived from the execution
context. S01 shipped the enum -- and left ``feedback_derived`` **unreachable**,
because ``resolve_lexicon_provenance`` had no branch that could ever return it.
S25 never noticed, since its two arms are L6 and ``review_item``.

S27 is the first slice to emit into L7 from a job, so it is the slice that
closes it. One branch on the SAME ``dispatch_route`` axis L6's twin uses -- not a
fourth discriminator (D3's amendment) -- so a mined lexicon proposal is
distinguishable from an admin's and from a capture fork's in every queue, which
is the whole point of FR-32.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.semantic_lexicon import (
    LEXICON_PROVENANCE_ADMIN_MANUAL,
    LEXICON_PROVENANCE_CONVERSATION_CONFIRMED,
    LEXICON_PROVENANCE_FEEDBACK_DERIVED,
    LEXICON_PROVENANCE_VALUES,
    create_semantic_lexicon_mock_handlers,
    resolve_lexicon_provenance,
)
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import execute_tool
from toee_hermes.plugin import register
from toee_hermes.tool_gate import (
    FEEDBACK_AGGREGATOR_ROUTE,
    TOOLS_DISPATCH_ROUTE,
    ToolExecutionContext,
)

INTERNAL = "internal_copilot"


def _ctx(**kwargs: Any) -> ToolExecutionContext:
    kwargs.setdefault("profile", INTERNAL)
    return ToolExecutionContext(**kwargs)


def _job_ctx() -> ToolExecutionContext:
    """What the mining job builds for itself -- a literal, and no actor."""
    return _ctx(dispatch_route=FEEDBACK_AGGREGATOR_ROUTE)


def test_the_l7_provenance_enum_carries_all_three_values() -> None:
    assert LEXICON_PROVENANCE_VALUES == (
        "admin_manual",
        "conversation_confirmed",
        "feedback_derived",
    )


def test_the_job_route_resolves_feedback_derived() -> None:
    assert resolve_lexicon_provenance(_job_ctx()) == LEXICON_PROVENANCE_FEEDBACK_DERIVED


@pytest.mark.parametrize(
    "context,expected",
    [
        # The capture fork / eval: internal profile, no route marker.
        (_ctx(), LEXICON_PROVENANCE_CONVERSATION_CONFIRMED),
        # An attributed rep's session -- an actor says WHO, never WHICH PATH.
        (_ctx(user_id="acct_rep_7"), LEXICON_PROVENANCE_CONVERSATION_CONFIRMED),
        # A route literal that is not the job's.
        (_ctx(dispatch_route="something-else"), LEXICON_PROVENANCE_CONVERSATION_CONFIRMED),
        # The admin BFF's deterministic dispatch route, D20-attributed.
        (
            _ctx(user_id="acct_admin_1", dispatch_route=TOOLS_DISPATCH_ROUTE),
            LEXICON_PROVENANCE_ADMIN_MANUAL,
        ),
    ],
)
def test_every_other_path_keeps_the_provenance_it_had(context, expected) -> None:
    """The S01/S02 branches are untouched: only the job's own route is new."""
    assert resolve_lexicon_provenance(context) == expected


def test_the_admin_route_still_fails_closed_without_an_actor() -> None:
    """D20 is not weakened by adding a branch in front of it."""
    with pytest.raises(ToolDriverError) as excinfo:
        resolve_lexicon_provenance(_ctx(dispatch_route=TOOLS_DISPATCH_ROUTE))
    assert excinfo.value.error_class == "policy_blocked"


def test_the_job_route_is_still_fail_closed_off_the_internal_profile() -> None:
    """Defence in depth: a route marker must not become a way past the profile."""
    with pytest.raises(ToolDriverError) as excinfo:
        resolve_lexicon_provenance(
            ToolExecutionContext(
                profile="customer_service_external",
                dispatch_route=FEEDBACK_AGGREGATOR_ROUTE,
            )
        )
    assert excinfo.value.error_class == "policy_blocked"


def _propose(context: ToolExecutionContext, **params: Any):
    params.setdefault("domain", "tire")
    params.setdefault("entry_kind", "alias")
    params.setdefault("surface_form", "mud")
    params.setdefault("canonical_form", "all-terrain")
    return execute_tool(
        tool="toee_semantic_lexicon",
        action="propose_lexicon_entry",
        params=params,
        context=context,
        driver=MockDriver(create_semantic_lexicon_mock_handlers()),
    )


def test_a_forged_provenance_param_cannot_produce_feedback_derived() -> None:
    """ADR-0148: the model-supplied value is ignored on the new branch too."""
    result = _propose(_ctx(), provenance=LEXICON_PROVENANCE_FEEDBACK_DERIVED)

    assert result.ok is True, result.message
    assert result.data["provenance"] == LEXICON_PROVENANCE_CONVERSATION_CONFIRMED


def test_the_job_route_stamps_feedback_derived_on_the_stored_row() -> None:
    result = _propose(_job_ctx())

    assert result.ok is True, result.message
    assert result.data["provenance"] == LEXICON_PROVENANCE_FEEDBACK_DERIVED
    assert result.data["status"] == "proposed"  # NFR-3: never confirmed by a job


class _RegistrationCtx:
    """Minimal stand-in for the Hermes plugin registration context (ADR-0139)."""

    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.handlers: dict[str, Any] = {}

    def register_tool(self, *, name: str, toolset: str, schema: dict, handler: Any) -> None:
        self.handlers[name] = handler

    def register_hook(self, event: str, callback: Any) -> None:
        pass


def test_the_agent_path_cannot_claim_the_job_route_via_a_runtime_kwarg() -> None:
    """The route marker is set by the SURFACE, never read from the agent loop's
    kwargs -- so nothing inside a turn can dress its own guess up as a mined
    proposal. The exact twin of L6's forged-kwarg test."""
    ctx = _RegistrationCtx(INTERNAL)
    register(ctx)
    handler = ctx.handlers["toee_semantic_lexicon__propose_lexicon_entry"]
    payload = json.loads(
        handler(
            {
                "domain": "tire",
                "entry_kind": "alias",
                "surface_form": "mud",
                "canonical_form": "all-terrain",
            },
            dispatch_route=FEEDBACK_AGGREGATOR_ROUTE,
            user_id="acct_rep_7",
        )
    )

    assert payload.get("error") is None, payload
    assert payload["provenance"] == LEXICON_PROVENANCE_CONVERSATION_CONFIRMED
