"""Launch Eval runner data shapes (ADR-0071, ADR-0072, ADR-0076, ADR-0119).

Ports packages/eval-runner/src/types.ts. Assertion sub-blocks are kept as raw
dicts/lists (structural passthrough, matching the TS loader) so the assertion
engine reads them directly and YAML parsing stays lossless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from toee_hermes.drivers.mock import (
    EasyroutesMockData,
    IdentityMockData,
    KnowledgeMockData,
    MemoryMockData,
    QboMockData,
    ShopifyMockData,
    SquareMockData,
)

# Launch Eval suites (ADR-0076). text_first_launch / email_go_live resolve
# scenario files directly; policy_publish is driven by the policy slot map.
EvalSuite = str  # "text_first_launch" | "email_go_live" | "policy_publish"
EvalSeverity = str  # "high" | "medium"

SUITE_VALUES: tuple[str, ...] = (
    "text_first_launch",
    "email_go_live",
    "policy_publish",
)


@dataclass(frozen=True)
class ScenarioTurn:
    """A single inbound turn: a plain SMS string or an email {body, subject?}."""

    inbound: Union[str, dict[str, str]]


@dataclass(frozen=True)
class ScenarioAssertions:
    """Standard assertion package (ADR-0072, ADR-0118).

    Only ``max_severity`` is required; the other blocks stay raw so the engine
    reads them without a rigid schema (matches the TS structural passthrough).
    """

    max_severity: EvalSeverity
    behavioral: Optional[dict[str, Any]] = None
    tool: Optional[dict[str, Any]] = None
    disclosure: Optional[dict[str, bool]] = None
    text: Optional[dict[str, Any]] = None
    memory_assertions: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ScenarioFixture:
    """A parsed scenario fixture, shape-validated but not yet merged with mocks."""

    scenario_id: str
    title: str
    suite: EvalSuite
    channel: str
    identity_preset: str
    turns: list[ScenarioTurn]
    mock_overrides: dict[str, Any]
    assertions: ScenarioAssertions
    memory_preset: Optional[dict[str, str]] = None


@dataclass(frozen=True)
class MergedMockContext:
    """Injectable mock data for every v1 Domain Adapter Tool.

    ``domain_errors`` marks domains a scenario forces into a governed failure
    (e.g. scenario 13 ``shopify.error: unavailable``).
    """

    identity: IdentityMockData
    shopify: ShopifyMockData
    qbo: QboMockData
    easyroutes: EasyroutesMockData
    square: SquareMockData
    knowledge: KnowledgeMockData
    memory: MemoryMockData
    domain_errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MergedScenario:
    """A scenario fully resolved against the baseline and ready to execute.

    ``session_identity`` is the Session Identity Snapshot as the snake_case dict
    the mock handlers read at ``context.identity`` (ADR-0043), per the merge order
    baseline -> identity_preset -> mock_overrides (ADR-0119, ADR-0073).
    """

    scenario_id: str
    title: str
    suite: EvalSuite
    channel: str
    identity_preset: str
    session_identity: dict[str, Any]
    turns: list[ScenarioTurn]
    assertions: ScenarioAssertions
    mock_context: MergedMockContext
    source_file: str
    memory_preset: Optional[dict[str, str]] = None


# base.yaml identity preset entry + parsed file. Presets stay raw dicts; v1 reads
# them for preset resolution, the full business records come from the
# domain-adapter baselines seeded from this same file (ADR-0073).
@dataclass(frozen=True)
class BaseMocks:
    identities: dict[str, dict[str, Any]]
