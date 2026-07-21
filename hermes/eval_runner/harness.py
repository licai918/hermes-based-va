"""Launch Eval agent harness (ports harness.ts, ADR-0071).

Composes a resolved scenario's mock context into a driver, forces any
error-marked domain into a governed failure (ADR-0020), and builds the External
Customer Service Profile execution context + Tool Gate every scenario runs under
(ADR-0034, ADR-0062). The agent itself is a deterministic stub so the runner,
report, and CLI gate are exercisable before the live turn is wired in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from toee_hermes.drivers.mock import (
    MockDriver,
    MockHandler,
    MockHandlerRegistry,
    create_admin_stub_mock_handlers,
    create_agent_experience_mock_handlers,
    create_case_mock_handlers,
    create_easyroutes_mock_handlers,
    create_identity_mock_handlers,
    create_knowledge_mock_handlers,
    create_memory_mock_handlers,
    create_qbo_mock_handlers,
    create_shopify_mock_handlers,
    create_square_mock_handlers,
    create_textline_mock_handlers,
    merge_registries,
)
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import ToolDriver
from toee_hermes.gates import create_external_profile_gate
from toee_hermes.plugin.profiles import EXTERNAL
from toee_hermes.tool_gate import ToolExecutionContext, ToolGate

from .types import MergedMockContext, MergedScenario


@dataclass(frozen=True)
class RecordedToolCall:
    """One tool call an agent turn performed, as recorded for tool assertions."""

    tool: str
    action: str
    ok: bool


@dataclass(frozen=True)
class AgentTurnResult:
    """The observable result of running an agent turn for a scenario.

    A real Hermes harness (later slice) populates these from the live turn; the
    stub returns an empty result so the runner, report, and CLI gate can be
    exercised now.
    """

    outbound_text: str = ""
    tool_calls: list[RecordedToolCall] = field(default_factory=list)
    case_created: bool = False
    disclosures: dict[str, bool] = field(default_factory=dict)
    memory_upserts: list[str] = field(default_factory=list)
    case_urgency: Optional[str] = None
    contact_reason: Optional[str] = None
    alternate_address_not_verified: Optional[bool] = None


class AgentHarness(Protocol):
    def run_turn(self, scenario: MergedScenario) -> AgentTurnResult: ...


class _StubAgentHarness:
    """Deterministic placeholder agent.

    It performs no tools and emits no text, so scenarios fail until the real
    External Customer Service harness is wired in. It exists so the eval runs
    end-to-end and the gate is provable.
    """

    def run_turn(self, scenario: MergedScenario) -> AgentTurnResult:
        return AgentTurnResult()


stub_agent_harness: AgentHarness = _StubAgentHarness()


# Domain key (as used in mock_overrides) -> the v1 tools it owns. Used to force a
# whole domain into a governed failure when a scenario sets ``<domain>.error``.
DOMAIN_TOOLS: dict[str, tuple[str, ...]] = {
    "identity": ("toee_identity_lookup",),
    "shopify": ("toee_shopify_read",),
    "qbo": ("toee_qbo_read",),
    "easyroutes": ("toee_easyroutes_read",),
    "square": ("toee_square_payment_link",),
    "knowledge": ("toee_knowledge_search",),
}


def _failing_handlers(
    handlers: dict[str, MockHandler], domain: str, reason: str
) -> dict[str, MockHandler]:
    def make_failure(_domain: str, _reason: str) -> MockHandler:
        def handler(_params: dict[str, object], _context: ToolExecutionContext) -> object:
            raise ToolDriverError(
                "vendor_timeout",
                f"{_domain} is temporarily unavailable ({_reason}).",
            )

        return handler

    return {action: make_failure(domain, reason) for action in handlers}


def build_scenario_registry(ctx: MergedMockContext) -> MockHandlerRegistry:
    """Compose the mock registry for a scenario, forcing error-marked domains.

    A domain marked with an error (e.g. scenario 13 ``shopify.error``) has every
    one of its tool's actions replaced with a governed ``vendor_timeout`` failure
    (ADR-0020); all other domains serve their merged baseline data.
    """
    registry: MockHandlerRegistry = merge_registries(
        create_identity_mock_handlers(ctx.identity),
        create_shopify_mock_handlers(ctx.shopify),
        create_qbo_mock_handlers(ctx.qbo),
        create_easyroutes_mock_handlers(ctx.easyroutes),
        create_square_mock_handlers(ctx.square),
        create_knowledge_mock_handlers(ctx.knowledge),
        create_memory_mock_handlers(ctx.memory),
        create_case_mock_handlers(),
        create_textline_mock_handlers(),
        create_admin_stub_mock_handlers(),
        create_agent_experience_mock_handlers(),
    )

    for domain, reason in ctx.domain_errors.items():
        for tool in DOMAIN_TOOLS.get(domain, ()):
            handlers = registry.get(tool)
            if handlers is None:
                continue
            registry[tool] = _failing_handlers(handlers, domain, reason)

    return registry


def create_scenario_driver(ctx: MergedMockContext) -> ToolDriver:
    return MockDriver(build_scenario_registry(ctx))


def scenario_execution_context(scenario: MergedScenario) -> ToolExecutionContext:
    """Build the Tool Gate execution context for a scenario run.

    Launch Eval always runs the External Customer Service Profile (ADR-0071); the
    Session Identity Snapshot rides in ``context.identity`` (ADR-0043).
    """
    return ToolExecutionContext(
        profile=EXTERNAL, identity=scenario.session_identity
    )


def scenario_tool_gate(scenario: MergedScenario) -> ToolGate:
    """Build the External profile Tool Gate from the scenario's email-link map.

    The Customer Email Link gate (ADR-0062) reads the merged ``qbo.email_links``
    so scenario overrides (e.g. scenario 04 ``failed``) deny the accounting read.
    """
    return create_external_profile_gate(email_links=scenario.mock_context.qbo.email_links)
