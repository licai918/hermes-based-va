import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  RESOLVED_AT,
  loadBaseMocks,
  loadScenario,
  loadSuite,
  parseScenarioContent,
  resolveScenario,
} from "./fixtures";

// packages/eval-runner/src -> repo root -> eval
const here = dirname(fileURLToPath(import.meta.url));
const evalDir = resolve(here, "../../../eval");

function base() {
  return loadBaseMocks(evalDir);
}

describe("loadBaseMocks", () => {
  it("reads identity presets from base.yaml", () => {
    const mocks = base();
    expect(mocks.identities.verified_customer_a).toMatchObject({
      phone: "+14165550101",
      shopify_customer_id: "gid://shopify/Customer/1001",
    });
    expect(mocks.identities.unmatched_phone?.phone).toBe("+14165550999");
    expect(mocks.identities.ambiguous_phone?.shopify_customer_ids).toHaveLength(
      2,
    );
    expect(mocks.identities.email_verified_a?.from_address).toBe(
      "accounts@acme-fleet.example",
    );
  });
});

describe("parseScenarioContent", () => {
  it("parses an SMS scenario with tool assertions", () => {
    const fixture = parseScenarioContent(
      `scenario_id: "01"\ntitle: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: verified_customer_a\nturns:\n  - inbound: hi\nmock_overrides: {}\nassertions:\n  tool:\n    expect_calls:\n      - tool: toee_shopify_read\n        action: get_order\n  max_severity: medium\n`,
      "01-x.yaml",
    );
    expect(fixture.scenario_id).toBe("01");
    expect(fixture.suite).toBe("text_first_launch");
    expect(fixture.assertions.tool?.expect_calls?.[0]).toEqual({
      tool: "toee_shopify_read",
      action: "get_order",
    });
  });

  it("parses an email object-form turn", () => {
    const fixture = parseScenarioContent(
      `scenario_id: "19"\ntitle: t\nsuite: email_go_live\nchannel: email\nidentity_preset: email_verified_a\nturns:\n  - inbound:\n      body: hello\n      subject: hi\nmock_overrides: {}\nassertions:\n  disclosure:\n    requires_email_support_signature: true\n  max_severity: medium\n`,
      "email/19-x.yaml",
    );
    expect(fixture.turns[0]?.inbound).toEqual({ body: "hello", subject: "hi" });
  });

  it("rejects a fixture missing scenario_id with a readable error", () => {
    expect(() =>
      parseScenarioContent(
        `title: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: x\nturns: []\nmock_overrides: {}\nassertions:\n  max_severity: medium\n`,
        "bad.yaml",
      ),
    ).toThrowError(/bad\.yaml.*scenario_id/s);
  });

  it("rejects a fixture whose scenario_id does not match the filename prefix", () => {
    expect(() =>
      parseScenarioContent(
        `scenario_id: "05"\ntitle: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: verified_customer_a\nturns:\n  - inbound: hi\nmock_overrides: {}\nassertions:\n  max_severity: medium\n`,
        "99-mismatch.yaml",
      ),
    ).toThrowError(/99-mismatch\.yaml.*05/s);
  });

  it("rejects a fixture missing max_severity", () => {
    expect(() =>
      parseScenarioContent(
        `scenario_id: "07"\ntitle: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: verified_customer_a\nturns:\n  - inbound: hi\nmock_overrides: {}\nassertions:\n  text:\n    must_contain: ["x"]\n`,
        "07-x.yaml",
      ),
    ).toThrowError(/max_severity/);
  });
});

describe("resolveScenario", () => {
  it("resolves a verified customer with a deterministic snapshot and linked accounting", () => {
    const fixture = parseScenarioContent(
      `scenario_id: "01"\ntitle: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: verified_customer_a\nturns:\n  - inbound: hi\nmock_overrides: {}\nassertions:\n  behavioral:\n    case_created: false\n  max_severity: medium\n`,
      "01-x.yaml",
    );
    const merged = resolveScenario(fixture, base(), "01-x.yaml");
    expect(merged.sessionIdentity).toEqual({
      outcome: "verified_customer",
      shopifyCustomerId: "gid://shopify/Customer/1001",
      resolvedAt: RESOLVED_AT,
    });
    expect(merged.mockContext.qbo.emailLinks["gid://shopify/Customer/1001"]).toBe(
      "linked",
    );
    // Square data is not in base.yaml; it comes from the adapter baseline.
    expect(merged.mockContext.square.payables.length).toBeGreaterThan(0);
    expect(merged.mockContext.domainErrors).toEqual({});
  });

  it("resolves an unmatched caller", () => {
    const fixture = parseScenarioContent(
      `scenario_id: "02"\ntitle: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: unmatched_phone\nturns:\n  - inbound: hi\nmock_overrides: {}\nassertions:\n  disclosure:\n    no_account_disclosure: true\n  max_severity: high\n`,
      "02-x.yaml",
    );
    const merged = resolveScenario(fixture, base(), "02-x.yaml");
    expect(merged.sessionIdentity.outcome).toBe("unmatched_caller");
  });

  it("resolves an ambiguous phone match with both candidate ids", () => {
    const fixture = parseScenarioContent(
      `scenario_id: "03"\ntitle: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: ambiguous_phone\nturns:\n  - inbound: hi\nmock_overrides: {}\nassertions:\n  text:\n    must_contain: ["order number"]\n  max_severity: medium\n`,
      "03-x.yaml",
    );
    const merged = resolveScenario(fixture, base(), "03-x.yaml");
    expect(merged.sessionIdentity).toMatchObject({
      outcome: "ambiguous_phone_match",
    });
    if (merged.sessionIdentity.outcome === "ambiguous_phone_match") {
      expect(merged.sessionIdentity.shopifyCustomerIds).toHaveLength(2);
    }
  });

  it("applies an email-link failure override (failed -> unlinked)", () => {
    const fixture = parseScenarioContent(
      `scenario_id: "04"\ntitle: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: verified_customer_a\nturns:\n  - inbound: hi\nmock_overrides:\n  qbo:\n    email_links:\n      verified_customer_a: failed\nassertions:\n  behavioral:\n    case_created: true\n  max_severity: high\n`,
      "04-x.yaml",
    );
    const merged = resolveScenario(fixture, base(), "04-x.yaml");
    expect(merged.mockContext.qbo.emailLinks["gid://shopify/Customer/1001"]).toBe(
      "unlinked",
    );
  });

  it("carries a domain error override (scenario 13)", () => {
    const fixture = parseScenarioContent(
      `scenario_id: "13"\ntitle: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: unmatched_phone\nturns:\n  - inbound: hi\nmock_overrides:\n  shopify:\n    error: unavailable\nassertions:\n  behavioral:\n    case_created: true\n  text:\n    must_contain: ["temporarily unavailable"]\n  max_severity: medium\n`,
      "13-x.yaml",
    );
    const merged = resolveScenario(fixture, base(), "13-x.yaml");
    expect(merged.mockContext.domainErrors.shopify).toBe("unavailable");
  });

  it("injects memory_preset into memory mock data", () => {
    const fixture = parseScenarioContent(
      `scenario_id: "25"\ntitle: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: verified_customer_a\nmemory_preset:\n  contact_time_preference: "after 2pm Eastern"\nturns:\n  - inbound: hi\nmock_overrides: {}\nassertions:\n  memory_assertions:\n    honor_injected_preference: true\n  max_severity: medium\n`,
      "25-x.yaml",
    );
    const merged = resolveScenario(fixture, base(), "25-x.yaml");
    expect(merged.memoryPreset?.contact_time_preference).toBe(
      "after 2pm Eastern",
    );
    expect(merged.mockContext.memory.preferences.contact_time_preference).toBe(
      "after 2pm Eastern",
    );
  });

  it("throws a readable error for an unknown identity_preset", () => {
    const fixture = parseScenarioContent(
      `scenario_id: "01"\ntitle: t\nsuite: text_first_launch\nchannel: textline\nidentity_preset: nope_preset\nturns:\n  - inbound: hi\nmock_overrides: {}\nassertions:\n  max_severity: medium\n`,
      "01-x.yaml",
    );
    expect(() => resolveScenario(fixture, base(), "01-x.yaml")).toThrowError(
      /nope_preset/,
    );
  });
});

describe("loadSuite / loadScenario against real fixtures", () => {
  it("loads the text_first_launch suite (SMS only, sorted, no email files)", () => {
    const scenarios = loadSuite("text_first_launch", evalDir);
    const ids = scenarios.map((s) => s.scenarioId);
    expect(ids).toContain("01");
    expect(ids).toContain("24");
    expect(ids).toContain("26");
    expect(scenarios.every((s) => s.suite === "text_first_launch")).toBe(true);
    // sorted ascending by id
    expect([...ids]).toEqual([...ids].sort());
    expect(scenarios.length).toBeGreaterThanOrEqual(20);
  });

  it("loads the email_go_live suite from the email subfolder", () => {
    const scenarios = loadSuite("email_go_live", evalDir);
    expect(scenarios.every((s) => s.suite === "email_go_live")).toBe(true);
    expect(scenarios.every((s) => s.channel === "email")).toBe(true);
    expect(scenarios.map((s) => s.scenarioId)).toContain("19");
  });

  it("loads a single scenario by suite and id", () => {
    const merged = loadScenario("text_first_launch", "05", evalDir);
    expect(merged.scenarioId).toBe("05");
    expect(merged.title).toMatch(/payment link/i);
  });

  it("throws when a scenario id is not found in the suite", () => {
    expect(() => loadScenario("text_first_launch", "99", evalDir)).toThrowError(
      /99/,
    );
  });
});
