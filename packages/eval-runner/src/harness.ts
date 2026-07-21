import {
  ToolDriverError,
  adminStubMockHandlers,
  createCaseMockHandlers,
  createEasyroutesMockHandlers,
  createIdentityMockHandlers,
  createKnowledgeMockHandlers,
  createMemoryMockHandlers,
  createMockDriver,
  createQboMockHandlers,
  createShopifyMockHandlers,
  createSquareMockHandlers,
  createSmsReplyMockHandlers,
  type MockHandlerRegistry,
  type MockToolHandlers,
  type ToolDriver,
  type ToolExecutionContext,
} from "@toee/domain-adapters";
import { HERMES_PROFILES, type ToolName } from "@toee/shared";
import type { MergedMockContext, MergedScenario } from "./types";

// One tool call an agent turn performed, as recorded for tool assertions.
export interface RecordedToolCall {
  tool: string;
  action: string;
  ok: boolean;
}

// The observable result of running an agent turn for a scenario. A real Hermes
// harness (later slice) populates these from the live turn; the stub returns an
// empty result so the runner, report, and CLI gate can be exercised now.
export interface AgentTurnResult {
  outboundText: string;
  toolCalls: RecordedToolCall[];
  caseCreated: boolean;
  caseUrgency?: string;
  contactReason?: string;
  alternateAddressNotVerified?: boolean;
  // Disclosure flag -> whether the turn satisfied it (harness-reported).
  disclosures: Record<string, boolean>;
  // Customer Memory preference slots the turn upserted.
  memoryUpserts: string[];
  // Whether the turn respected an injected memory_preset without re-asking.
  honoredInjectedPreference?: boolean;
}

export interface AgentHarness {
  runTurn(scenario: MergedScenario): AgentTurnResult | Promise<AgentTurnResult>;
}

// Deterministic placeholder agent. It performs no tools and emits no text, so
// scenarios fail until the real External Customer Service harness is wired in
// (#13+). It exists so `pnpm eval` runs end-to-end and the gate is provable.
export const stubAgentHarness: AgentHarness = {
  runTurn(): AgentTurnResult {
    return {
      outboundText: "",
      toolCalls: [],
      caseCreated: false,
      disclosures: {},
      memoryUpserts: [],
    };
  },
};

// Domain key (as used in mock_overrides) -> the v1 tools it owns. Used to force
// a whole domain into a governed failure when a scenario sets `<domain>.error`.
const DOMAIN_TOOLS: Partial<Record<string, ToolName[]>> = {
  identity: ["toee_identity_lookup"],
  shopify: ["toee_shopify_read"],
  qbo: ["toee_qbo_read"],
  easyroutes: ["toee_easyroutes_read"],
  square: ["toee_square_payment_link"],
  knowledge: ["toee_knowledge_search"],
};

// Composes a mock handler registry from a resolved scenario's mock context and
// forces any error-marked domain to return a governed failure (ADR-0020).
export function buildScenarioRegistry(
  ctx: MergedMockContext,
): MockHandlerRegistry {
  const registry: MockHandlerRegistry = {
    ...createIdentityMockHandlers(ctx.identity),
    ...createShopifyMockHandlers(ctx.shopify),
    ...createQboMockHandlers(ctx.qbo),
    ...createEasyroutesMockHandlers(ctx.easyroutes),
    ...createSquareMockHandlers(ctx.square),
    ...createKnowledgeMockHandlers(ctx.knowledge),
    ...createMemoryMockHandlers(ctx.memory),
    ...createCaseMockHandlers(),
    ...createSmsReplyMockHandlers(),
    ...adminStubMockHandlers,
  };

  for (const [domain, reason] of Object.entries(ctx.domainErrors)) {
    for (const tool of DOMAIN_TOOLS[domain] ?? []) {
      const handlers = registry[tool];
      if (handlers === undefined) {
        continue;
      }
      const failing: MockToolHandlers = {};
      for (const action of Object.keys(handlers)) {
        failing[action] = () => {
          throw new ToolDriverError(
            "vendor_timeout",
            `${domain} is temporarily unavailable (${reason}).`,
          );
        };
      }
      registry[tool] = failing;
    }
  }

  return registry;
}

export function createScenarioDriver(ctx: MergedMockContext): ToolDriver {
  return createMockDriver(buildScenarioRegistry(ctx));
}

// Builds the Tool Gate execution context for a scenario run. Launch eval always
// runs the External Customer Service Profile (ADR-0071).
export function scenarioExecutionContext(
  scenario: MergedScenario,
): ToolExecutionContext {
  return {
    profile: HERMES_PROFILES.externalCustomerService,
    identity: scenario.sessionIdentity,
  };
}
