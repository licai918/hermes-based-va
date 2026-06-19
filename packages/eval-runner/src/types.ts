import type {
  CustomerPreferenceSlots,
  EasyRoutesMockData,
  IdentityMockData,
  KnowledgeMockData,
  MemoryMockData,
  QboMockData,
  ShopifyMockData,
  SquareMockData,
} from "@toee/domain-adapters";
import type { SessionIdentitySnapshot } from "@toee/shared";

// Launch Eval suites (ADR-0076). `text_first_launch` and `email_go_live` resolve
// scenario files directly; `policy_publish` is driven by the policy slot map.
export type EvalSuite = "text_first_launch" | "email_go_live" | "policy_publish";

export type EvalSeverity = "high" | "medium";

// A single inbound turn. SMS turns are plain strings; email turns carry an
// object with body and optional subject (ADR-0124).
export type ScenarioTurn = {
  inbound: string | { body: string; subject?: string };
};

// One expected/forbidden tool call. `action` is optional so a scenario can
// assert a tool was (not) used regardless of action.
export interface ToolCallAssertion {
  tool: string;
  action?: string;
}

export interface MemoryAssertions {
  expect_upsert?: boolean;
  expect_upsert_slot?: string;
  forbid_inferred_upsert?: boolean;
  honor_injected_preference?: boolean;
}

// The standard assertion package (ADR-0072, ADR-0118). All blocks are optional
// except `max_severity`; the minimum-composition rule is a fixture-authoring
// convention, not enforced by the loader, so shipped fixtures like scenario 25
// (memory + text only) load cleanly.
export interface ScenarioAssertions {
  behavioral?: Record<string, unknown>;
  tool?: {
    expect_calls?: ToolCallAssertion[];
    forbidden_tools?: ToolCallAssertion[];
  };
  disclosure?: Record<string, boolean>;
  text?: {
    must_contain?: string[];
    must_not_contain?: string[];
  };
  memory_assertions?: MemoryAssertions;
  max_severity: EvalSeverity;
}

// A parsed scenario fixture file, shape-validated but not yet merged with mocks.
export interface ScenarioFixture {
  scenario_id: string;
  title: string;
  suite: EvalSuite;
  channel: string;
  identity_preset: string;
  memory_preset?: CustomerPreferenceSlots;
  turns: ScenarioTurn[];
  mock_overrides: Record<string, unknown>;
  assertions: ScenarioAssertions;
}

// Injectable mock data for every v1 Domain Adapter Tool, shaped for the
// create*MockHandlers factories. `domainErrors` marks domains a scenario forces
// into a governed failure (e.g. scenario 13 `shopify.error: unavailable`).
export interface MergedMockContext {
  identity: IdentityMockData;
  shopify: ShopifyMockData;
  qbo: QboMockData;
  easyroutes: EasyRoutesMockData;
  square: SquareMockData;
  knowledge: KnowledgeMockData;
  memory: MemoryMockData;
  domainErrors: Record<string, string>;
}

// A scenario fully resolved against the shared baseline and ready to execute:
// the active Session Identity Snapshot plus injectable mock data per the runner
// merge order in ADR-0119 (baseline -> identity_preset -> mock_overrides).
export interface MergedScenario {
  scenarioId: string;
  title: string;
  suite: EvalSuite;
  channel: string;
  identityPreset: string;
  sessionIdentity: SessionIdentitySnapshot;
  turns: ScenarioTurn[];
  assertions: ScenarioAssertions;
  memoryPreset?: CustomerPreferenceSlots;
  mockContext: MergedMockContext;
  sourceFile: string;
}

// base.yaml identity preset entry. Verified presets carry a single
// shopify_customer_id; ambiguous presets carry several; unmatched presets carry
// neither. SMS presets key on phone, email presets on from_address.
export interface BaseIdentityPreset {
  phone?: string;
  from_address?: string;
  shopify_customer_id?: string;
  shopify_customer_ids?: string[];
  email?: string;
  company_name?: string;
}

// Parsed eval/mocks/base.yaml. v1 reads identities for preset resolution; the
// complete business records come from the domain-adapter baselines, which were
// seeded from this same file (ADR-0073).
export interface BaseMocks {
  identities: Record<string, BaseIdentityPreset>;
}
