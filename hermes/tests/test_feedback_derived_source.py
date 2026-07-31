"""0.0.5 S25 (FR-32, D3): L6's ``feedback_derived`` source, framework-derived.

D3 gives S25 one job in this package: add ``feedback_derived`` to the L6 source
enum and the matching branch in ``resolve_agent_experience_source`` -- keyed on
the AGGREGATOR JOB'S OWN execution context, never on a caller param. The 0.0.3
INTERNAL -> ``copilot_agent`` branch and its forged-param test stay exactly as
they are (``test_agent_experience.py`` is untouched); this file adds the
equivalent forged-param coverage for the new branch.

**The discriminator is ``dispatch_route``, not a fourth mechanism.** S01 already
shipped a framework-set route marker on ``ToolExecutionContext`` and keyed L7's
provenance on it; D3's amendment says S25 keys L6's source on the SAME axis so
every layer shares one provenance discriminator instead of three that drift.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from toee_hermes.drivers.mock.agent_experience import (
    AGENT_EXPERIENCE_SOURCE_COPILOT_AGENT,
    AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED,
    AGENT_EXPERIENCE_SOURCE_VALUES,
    create_agent_experience_mock_handlers,
    resolve_agent_experience_source,
)
from toee_hermes.drivers.mock.driver import MockDriver
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


def _aggregator_ctx() -> ToolExecutionContext:
    """What the scheduled job builds for itself -- a literal, no actor."""
    return _ctx(dispatch_route=FEEDBACK_AGGREGATOR_ROUTE)


# --- the enum (D3) ------------------------------------------------------------


def test_the_l6_source_enum_carries_both_values() -> None:
    # Without feedback_derived an aggregator proposal is indistinguishable from
    # an agent-proposed one in every queue -- the one thing FR-32 exists to give.
    assert AGENT_EXPERIENCE_SOURCE_VALUES == ("copilot_agent", "feedback_derived")


# --- the resolver branch ------------------------------------------------------


def test_the_aggregator_route_resolves_feedback_derived() -> None:
    assert (
        resolve_agent_experience_source(_aggregator_ctx())
        == AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED
    )


@pytest.mark.parametrize(
    "context",
    [
        # The copilot review fork (S23): internal profile, no route marker.
        _ctx(),
        # An attributed rep's session -- an actor says WHO, not WHICH PATH.
        _ctx(user_id="acct_rep_7"),
        # The admin BFF's deterministic dispatch route.
        _ctx(user_id="acct_admin_1", dispatch_route=TOOLS_DISPATCH_ROUTE),
        # A route literal that is not the aggregator's.
        _ctx(dispatch_route="something-else"),
    ],
)
def test_every_other_internal_path_still_resolves_copilot_agent(context) -> None:
    # The 0.0.3 branch is unchanged: only the aggregator's own route is new.
    assert (
        resolve_agent_experience_source(context)
        == AGENT_EXPERIENCE_SOURCE_COPILOT_AGENT
    )


def test_the_aggregator_route_is_still_fail_closed_off_the_internal_profile() -> None:
    # Defence in depth: the profile allowlist already keeps L6 unreachable
    # elsewhere, and a route marker must not become a way around it.
    with pytest.raises(ToolDriverError) as excinfo:
        resolve_agent_experience_source(
            ToolExecutionContext(
                profile="customer_service_external",
                dispatch_route=FEEDBACK_AGGREGATOR_ROUTE,
            )
        )
    assert excinfo.value.error_class == "policy_blocked"


# --- forged params / forged kwargs (ADR-0148) ---------------------------------


def _propose(context: ToolExecutionContext, **params: Any):
    params.setdefault("kind", "procedure")
    params.setdefault("content", "A harmless operational note.")
    return execute_tool(
        tool="toee_agent_experience",
        action="propose_experience",
        params=params,
        context=context,
        driver=MockDriver(create_agent_experience_mock_handlers()),
    )


def test_a_forged_source_param_cannot_produce_feedback_derived() -> None:
    # D3's required twin of test_propose_experience_source_cannot_be_forged: a
    # model-supplied "source" is ignored on the new branch exactly as on the old.
    result = _propose(_ctx(), source=AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED)

    assert result.ok is True
    assert result.data["source"] == AGENT_EXPERIENCE_SOURCE_COPILOT_AGENT


def test_the_aggregator_route_stamps_feedback_derived_on_the_stored_row() -> None:
    result = _propose(_aggregator_ctx())

    assert result.ok is True, result.message
    assert result.data["source"] == AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED


class _RegistrationCtx:
    """Minimal stand-in for the Hermes plugin registration context (ADR-0139)."""

    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.handlers: dict[str, Any] = {}

    def register_tool(self, *, name: str, toolset: str, schema: dict, handler: Any) -> None:
        self.handlers[name] = handler

    def register_hook(self, event: str, callback: Any) -> None:
        pass


def test_the_agent_path_cannot_claim_the_aggregator_route_via_a_runtime_kwarg() -> None:
    # The route marker is set by the SURFACE, never read from the kwargs the
    # agent loop hands a tool handler -- so nothing reachable from inside a turn
    # can dress its own guess up as a feedback-derived proposal. Mirrors
    # test_semantic_lexicon.py's twin for the L7 provenance axis.
    ctx = _RegistrationCtx(INTERNAL)
    register(ctx)
    handler = ctx.handlers["toee_agent_experience__propose_experience"]
    payload = json.loads(
        handler(
            {"kind": "procedure", "content": "A harmless operational note."},
            dispatch_route=FEEDBACK_AGGREGATOR_ROUTE,
            user_id="acct_rep_7",
        )
    )

    assert payload.get("error") is None, payload
    assert payload["source"] == AGENT_EXPERIENCE_SOURCE_COPILOT_AGENT
