import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { parse as parseYaml } from "yaml";
import {
  easyroutesBaselineData,
  identityBaselineData,
  knowledgeBaselineData,
  memoryBaselineData,
  qboBaselineData,
  shopifyBaselineData,
  squareBaselineData,
  type QboEmailLinkStatus,
  type ShopifyOrder,
  type ShopifyProduct,
} from "@toee/domain-adapters";
import type { SessionIdentitySnapshot } from "@toee/shared";
import type {
  BaseIdentityPreset,
  BaseMocks,
  EvalSuite,
  MergedMockContext,
  MergedScenario,
  ScenarioAssertions,
  ScenarioFixture,
  ScenarioTurn,
} from "./types";

// Deterministic Session Identity Snapshot timestamp. Ingress resolves identity
// before the turn (ADR-0043); eval pins it so reports never depend on wall time.
export const RESOLVED_AT = "2026-01-01T00:00:00.000Z";

const SUITE_VALUES: readonly EvalSuite[] = [
  "text_first_launch",
  "email_go_live",
  "policy_publish",
];

function lastSegment(label: string): string {
  return label.split(/[\\/]/).pop() ?? label;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// ---------------------------------------------------------------------------
// base.yaml
// ---------------------------------------------------------------------------

export function loadBaseMocks(evalDir: string): BaseMocks {
  const path = join(evalDir, "mocks", "base.yaml");
  if (!existsSync(path)) {
    throw new Error(`Eval base mocks not found at ${path}.`);
  }
  let raw: unknown;
  try {
    raw = parseYaml(readFileSync(path, "utf8"));
  } catch (error) {
    throw new Error(`Failed to parse ${path}: ${(error as Error).message}`);
  }
  if (!isObject(raw) || !isObject(raw.identities)) {
    throw new Error(`Eval base mocks at ${path} must define "identities".`);
  }
  return { identities: raw.identities as Record<string, BaseIdentityPreset> };
}

// ---------------------------------------------------------------------------
// Scenario fixture parsing + validation
// ---------------------------------------------------------------------------

function fail(label: string, message: string): never {
  throw new Error(`Scenario ${label}: ${message}`);
}

function requireString(
  raw: Record<string, unknown>,
  field: string,
  label: string,
): string {
  const value = raw[field];
  if (typeof value !== "string" || value.length === 0) {
    fail(label, `missing required "${field}".`);
  }
  return value as string;
}

function validateTurns(raw: unknown, label: string): ScenarioTurn[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    fail(label, `"turns" must be a non-empty list.`);
  }
  return (raw as unknown[]).map((turn, index) => {
    if (!isObject(turn) || !("inbound" in turn)) {
      fail(label, `turn ${index} must define "inbound".`);
    }
    const inbound = (turn as Record<string, unknown>).inbound;
    if (typeof inbound === "string") {
      return { inbound };
    }
    if (isObject(inbound) && typeof inbound.body === "string") {
      return {
        inbound: {
          body: inbound.body,
          ...(typeof inbound.subject === "string"
            ? { subject: inbound.subject }
            : {}),
        },
      };
    }
    fail(label, `turn ${index} "inbound" must be a string or { body }.`);
  });
}

function validateAssertions(raw: unknown, label: string): ScenarioAssertions {
  if (!isObject(raw)) {
    fail(label, `"assertions" must be an object.`);
  }
  const severity = (raw as Record<string, unknown>).max_severity;
  if (severity !== "high" && severity !== "medium") {
    fail(label, `"assertions.max_severity" must be "high" or "medium".`);
  }
  // Blocks are passed through structurally; the assertion engine (#10) reads
  // them. The loader only enforces the required severity gate here.
  return raw as unknown as ScenarioAssertions;
}

export function parseScenarioContent(
  content: string,
  label: string,
): ScenarioFixture {
  let raw: unknown;
  try {
    raw = parseYaml(content);
  } catch (error) {
    throw new Error(`Failed to parse ${label}: ${(error as Error).message}`);
  }
  if (!isObject(raw)) {
    fail(label, `file is not a YAML mapping.`);
  }

  const scenarioId = requireString(raw, "scenario_id", label);

  // scenario_id must match the numeric filename prefix (ADR-0119).
  const prefixMatch = lastSegment(label).match(/^(\d+)/);
  if (prefixMatch) {
    const filePrefix = Number.parseInt(prefixMatch[1] as string, 10);
    const idNumber = Number.parseInt(scenarioId, 10);
    if (Number.isNaN(idNumber) || filePrefix !== idNumber) {
      fail(
        label,
        `scenario_id "${scenarioId}" does not match filename numeric prefix "${prefixMatch[1]}".`,
      );
    }
  }

  const suite = requireString(raw, "suite", label) as EvalSuite;
  if (!SUITE_VALUES.includes(suite)) {
    fail(label, `unknown suite "${suite}".`);
  }

  const memoryPreset = raw.memory_preset;
  if (memoryPreset !== undefined && !isObject(memoryPreset)) {
    fail(label, `"memory_preset" must be an object when present.`);
  }

  const mockOverrides = raw.mock_overrides ?? {};
  if (!isObject(mockOverrides)) {
    fail(label, `"mock_overrides" must be an object.`);
  }

  return {
    scenario_id: scenarioId,
    title: requireString(raw, "title", label),
    suite,
    channel: requireString(raw, "channel", label),
    identity_preset: requireString(raw, "identity_preset", label),
    ...(memoryPreset !== undefined
      ? { memory_preset: memoryPreset as ScenarioFixture["memory_preset"] }
      : {}),
    turns: validateTurns(raw.turns, label),
    mock_overrides: mockOverrides as Record<string, unknown>,
    assertions: validateAssertions(raw.assertions, label),
  };
}

export function parseScenarioFile(path: string): ScenarioFixture {
  return parseScenarioContent(readFileSync(path, "utf8"), path);
}

// ---------------------------------------------------------------------------
// Merge: baseline -> identity_preset -> mock_overrides (ADR-0119, ADR-0073)
// ---------------------------------------------------------------------------

function buildSessionIdentity(
  preset: BaseIdentityPreset,
): SessionIdentitySnapshot {
  if (typeof preset.shopify_customer_id === "string") {
    return {
      outcome: "verified_customer",
      shopifyCustomerId: preset.shopify_customer_id,
      resolvedAt: RESOLVED_AT,
    };
  }
  if (
    Array.isArray(preset.shopify_customer_ids) &&
    preset.shopify_customer_ids.length > 0
  ) {
    return {
      outcome: "ambiguous_phone_match",
      shopifyCustomerIds: [...preset.shopify_customer_ids],
      resolvedAt: RESOLVED_AT,
    };
  }
  return { outcome: "unmatched_caller", resolvedAt: RESOLVED_AT };
}

function freshMockContext(): MergedMockContext {
  return {
    identity: structuredClone(identityBaselineData),
    shopify: structuredClone(shopifyBaselineData),
    qbo: structuredClone(qboBaselineData),
    easyroutes: structuredClone(easyroutesBaselineData),
    square: structuredClone(squareBaselineData),
    knowledge: structuredClone(knowledgeBaselineData),
    memory: structuredClone(memoryBaselineData),
    domainErrors: {},
  };
}

function normalizeEmailLink(value: unknown): QboEmailLinkStatus {
  // base/override use linked|failed|unlinked; the mock enum is linked|unlinked,
  // so any non-linked state (e.g. scenario 04 "failed") collapses to unlinked.
  return value === "linked" ? "linked" : "unlinked";
}

function applyEmailLinkOverrides(
  context: MergedMockContext,
  base: BaseMocks,
  overrides: Record<string, unknown>,
): void {
  for (const [presetKey, rawStatus] of Object.entries(overrides)) {
    const customerId = base.identities[presetKey]?.shopify_customer_id;
    if (customerId === undefined) {
      continue;
    }
    const status = normalizeEmailLink(rawStatus);
    context.qbo.emailLinks[customerId] = status;
    context.identity.emailLinks[customerId] = status;
    const email = base.identities[presetKey]?.email;
    if (email !== undefined) {
      context.identity.emailLinks[email] = status;
    }
  }
}

function toShopifyOrder(
  raw: Record<string, unknown>,
  fallbackCustomerId: string | undefined,
): ShopifyOrder {
  const lineItems = Array.isArray(raw.line_items)
    ? (raw.line_items as Record<string, unknown>[]).map((item) => ({
        sku: String(item.sku ?? ""),
        title: String(item.title ?? ""),
      }))
    : [];
  return {
    orderNumber: String(raw.order_number ?? ""),
    customerId: String(raw.customer_id ?? fallbackCustomerId ?? ""),
    lineItems,
  };
}

function applyShopifyOrderOverrides(
  context: MergedMockContext,
  rawOrders: Record<string, unknown>,
  activeCustomerId: string | undefined,
): void {
  const incoming: ShopifyOrder[] = [];
  for (const value of Object.values(rawOrders)) {
    const entries = Array.isArray(value) ? value : [value];
    for (const entry of entries) {
      if (isObject(entry)) {
        incoming.push(toShopifyOrder(entry, activeCustomerId));
      }
    }
  }
  // Upsert by orderNumber so an override replaces the baseline order it shadows.
  for (const order of incoming) {
    const index = context.shopify.orders.findIndex(
      (existing) => existing.orderNumber === order.orderNumber,
    );
    if (index >= 0) {
      context.shopify.orders[index] = order;
    } else {
      context.shopify.orders.push(order);
    }
  }
}

function applyShopifyProductOverrides(
  context: MergedMockContext,
  rawProducts: Record<string, unknown>,
): void {
  for (const [key, value] of Object.entries(rawProducts)) {
    if (!isObject(value)) {
      continue;
    }
    const sku = typeof value.sku === "string" ? value.sku : undefined;
    const existing = context.shopify.products.find(
      (product) => sku !== undefined && product.sku === sku,
    );
    const patch: Partial<ShopifyProduct> = {
      ...(sku !== undefined ? { sku } : {}),
      ...(typeof value.title === "string" ? { title: value.title } : {}),
      ...(typeof value.product_url === "string"
        ? { productUrl: value.product_url }
        : {}),
      ...(typeof value.media_url === "string"
        ? { mediaUrl: value.media_url }
        : {}),
      ...(value.price !== undefined ? { price: String(value.price) } : {}),
      ...(typeof value.inventory === "number"
        ? { inventory: value.inventory }
        : {}),
    };
    if (existing) {
      Object.assign(existing, patch);
    } else {
      context.shopify.products.push({
        productId: `gid://shopify/Product/mock-${key}`,
        sku: sku ?? key,
        title: typeof value.title === "string" ? value.title : (sku ?? key),
        productUrl:
          typeof value.product_url === "string" ? value.product_url : "",
        mediaUrl: typeof value.media_url === "string" ? value.media_url : "",
        ...(value.price !== undefined ? { price: String(value.price) } : {}),
        ...(typeof value.inventory === "number"
          ? { inventory: value.inventory }
          : {}),
      });
    }
  }
}

function applyOperationalPolicyOverrides(
  context: MergedMockContext,
  rawPolicy: Record<string, unknown>,
): void {
  for (const [slot, value] of Object.entries(rawPolicy)) {
    if (value === "empty" || value === "" || value === null) {
      // Explicitly empty slot -> governed no-policy fallback (ADR-0067).
      delete context.knowledge.operationalPolicy[slot];
    } else {
      context.knowledge.operationalPolicy[slot] = String(value);
    }
  }
}

function applyMockOverrides(
  context: MergedMockContext,
  base: BaseMocks,
  overrides: Record<string, unknown>,
  activeCustomerId: string | undefined,
): void {
  for (const [domain, raw] of Object.entries(overrides)) {
    if (!isObject(raw)) {
      continue;
    }
    // A domain marked with an `error` is forced into a governed failure for
    // this scenario (e.g. scenario 13 shopify.error: unavailable).
    if (typeof raw.error === "string") {
      context.domainErrors[domain] = raw.error;
    }
    if (domain === "qbo" && isObject(raw.email_links)) {
      applyEmailLinkOverrides(context, base, raw.email_links);
    }
    if (domain === "shopify" && isObject(raw.orders)) {
      applyShopifyOrderOverrides(context, raw.orders, activeCustomerId);
    }
    if (domain === "shopify" && isObject(raw.products)) {
      applyShopifyProductOverrides(context, raw.products);
    }
    if (domain === "knowledge" && isObject(raw.operational_policy)) {
      applyOperationalPolicyOverrides(context, raw.operational_policy);
    }
  }
}

export function resolveScenario(
  fixture: ScenarioFixture,
  base: BaseMocks,
  sourceFile: string,
): MergedScenario {
  const preset = base.identities[fixture.identity_preset];
  if (preset === undefined) {
    fail(sourceFile, `unknown identity_preset "${fixture.identity_preset}".`);
  }

  const sessionIdentity = buildSessionIdentity(preset);
  const activeCustomerId =
    sessionIdentity.outcome === "verified_customer"
      ? sessionIdentity.shopifyCustomerId
      : undefined;

  const mockContext = freshMockContext();
  if (fixture.memory_preset !== undefined) {
    mockContext.memory.preferences = { ...fixture.memory_preset };
  }
  applyMockOverrides(mockContext, base, fixture.mock_overrides, activeCustomerId);

  return {
    scenarioId: fixture.scenario_id,
    title: fixture.title,
    suite: fixture.suite,
    channel: fixture.channel,
    identityPreset: fixture.identity_preset,
    sessionIdentity,
    turns: fixture.turns,
    assertions: fixture.assertions,
    ...(fixture.memory_preset !== undefined
      ? { memoryPreset: fixture.memory_preset }
      : {}),
    mockContext,
    sourceFile,
  };
}

// ---------------------------------------------------------------------------
// Suite discovery
// ---------------------------------------------------------------------------

function scenarioFilesFor(evalDir: string, suite: EvalSuite): string[] {
  const scenariosDir = join(evalDir, "scenarios");
  if (suite === "email_go_live") {
    const emailDir = join(scenariosDir, "email");
    if (!existsSync(emailDir)) {
      return [];
    }
    return readdirSync(emailDir)
      .filter((name) => name.endsWith(".yaml"))
      .map((name) => join(emailDir, name));
  }
  // text_first_launch / policy_publish source from the top-level scenarios dir.
  return readdirSync(scenariosDir)
    .filter((name) => name.endsWith(".yaml"))
    .map((name) => join(scenariosDir, name));
}

export function loadSuite(suite: EvalSuite, evalDir: string): MergedScenario[] {
  const base = loadBaseMocks(evalDir);
  const merged: MergedScenario[] = [];
  for (const file of scenarioFilesFor(evalDir, suite)) {
    const fixture = parseScenarioFile(file);
    if (fixture.suite !== suite) {
      continue;
    }
    merged.push(resolveScenario(fixture, base, file));
  }
  merged.sort((a, b) => a.scenarioId.localeCompare(b.scenarioId));
  return merged;
}

export function loadScenario(
  suite: EvalSuite,
  scenarioId: string,
  evalDir: string,
): MergedScenario {
  const target = Number.parseInt(scenarioId, 10);
  const match = loadSuite(suite, evalDir).find(
    (scenario) => Number.parseInt(scenario.scenarioId, 10) === target,
  );
  if (match === undefined) {
    throw new Error(
      `Scenario "${scenarioId}" not found in suite "${suite}".`,
    );
  }
  return match;
}

// ---------------------------------------------------------------------------
// policy_publish suite (ADR-0075, ADR-0121)
// ---------------------------------------------------------------------------

export interface PolicySlotMap {
  regression_subset: number[];
  slots: Record<string, { scenario_ids: number[] }>;
}

export function loadPolicySlotMap(evalDir: string): PolicySlotMap {
  const path = join(evalDir, "policy_slot_map.yaml");
  if (!existsSync(path)) {
    throw new Error(`Policy slot map not found at ${path}.`);
  }
  let raw: unknown;
  try {
    raw = parseYaml(readFileSync(path, "utf8"));
  } catch (error) {
    throw new Error(`Failed to parse ${path}: ${(error as Error).message}`);
  }
  if (!isObject(raw) || !isObject(raw.slots)) {
    throw new Error(`Policy slot map at ${path} must define "slots".`);
  }
  return {
    regression_subset: Array.isArray(raw.regression_subset)
      ? (raw.regression_subset as number[])
      : [],
    slots: raw.slots as PolicySlotMap["slots"],
  };
}

// A policy_publish run executes the scenarios mapped to one Required Operational
// Policy Slot plus the standing regression subset (ADR-0075).
export function loadPolicyPublishSuite(
  evalDir: string,
  slot: string,
): MergedScenario[] {
  const map = loadPolicySlotMap(evalDir);
  const slotDef = map.slots[slot];
  if (slotDef === undefined) {
    throw new Error(
      `Unknown policy slot "${slot}" in ${join(evalDir, "policy_slot_map.yaml")}.`,
    );
  }
  const ids = new Set<number>([
    ...(slotDef.scenario_ids ?? []),
    ...map.regression_subset,
  ]);
  return loadSuite("text_first_launch", evalDir).filter((scenario) =>
    ids.has(Number.parseInt(scenario.scenarioId, 10)),
  );
}
