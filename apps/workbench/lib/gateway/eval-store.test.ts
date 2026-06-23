import { describe, expect, it, beforeEach } from "vitest";
import {
  createInMemoryEvalStore,
  type EvalRunReport,
  type EvalStore,
} from "./eval-store";

function report(overrides: Partial<EvalRunReport> & { run_id: string }): EvalRunReport {
  return {
    suite: "text_first_launch",
    model_slug: "deepseek/deepseek-v4-pro",
    prompt_version: "v1",
    knowledge_version: "v1",
    timestamp: "2026-06-01T00:00:00Z",
    scenarios: [],
    summary: { total: 1, passed: 1, failed_high: 0, failed_medium: 0 },
    signoff_required: false,
    ...overrides,
  };
}

const PASS = report({ run_id: "tfl-001", timestamp: "2026-06-03T00:00:00Z" });
const MEDIUM = report({
  run_id: "pp-001",
  suite: "policy_publish",
  timestamp: "2026-06-02T00:00:00Z",
  summary: { total: 10, passed: 9, failed_high: 0, failed_medium: 1 },
  signoff_required: true,
});
const HIGH = report({
  run_id: "tfl-000",
  timestamp: "2026-06-01T00:00:00Z",
  summary: { total: 5, passed: 4, failed_high: 1, failed_medium: 0 },
  signoff_required: false,
});

let store: EvalStore;
beforeEach(() => {
  store = createInMemoryEvalStore([PASS, MEDIUM, HIGH]);
});

describe("listRuns", () => {
  it("lists runs most recent first", () => {
    expect(store.listRuns().map((r) => r.run_id)).toEqual(["tfl-001", "pp-001", "tfl-000"]);
  });
});

describe("getRun", () => {
  it("returns the full report", () => {
    expect(store.getRun("pp-001")?.suite).toBe("policy_publish");
  });
  it("returns undefined for an unknown run", () => {
    expect(store.getRun("nope")).toBeUndefined();
  });
});

describe("signOffMedium", () => {
  it("signs off a medium-only failure run and reflects it on the report", () => {
    expect(store.signOffMedium("pp-001", "seed-admin").ok).toBe(true);
    expect(store.getRun("pp-001")?.signed_off).toBe(true);
  });
  it("refuses when no medium sign-off is required", () => {
    expect(store.signOffMedium("tfl-001", "seed-admin")).toEqual({ ok: false, reason: "not_required" });
  });
  it("refuses when high-severity failures remain", () => {
    expect(store.signOffMedium("tfl-000", "seed-admin")).toEqual({ ok: false, reason: "failed_high" });
  });
});

describe("promotePending", () => {
  it("refuses to promote a non-policy_publish run", () => {
    expect(store.promotePending("tfl-001")).toEqual({ ok: false, reason: "not_promotable" });
  });
  it("blocks promotion until the medium failure is signed off", () => {
    expect(store.promotePending("pp-001")).toEqual({ ok: false, reason: "signoff_required" });
  });
  it("promotes a policy_publish run once signed off", () => {
    store.signOffMedium("pp-001", "seed-admin");
    expect(store.promotePending("pp-001").ok).toBe(true);
    expect(store.getRun("pp-001")?.promoted).toBe(true);
  });
});
