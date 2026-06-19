import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { AgentHarness } from "./harness";
import { buildReport, writeReport, type ScenarioOutcome } from "./report";
import { runSuite } from "./run";

const here = dirname(fileURLToPath(import.meta.url));
const evalDir = resolve(here, "../../../eval");

describe("buildReport", () => {
  it("summarizes pass/fail counts by scenario severity", () => {
    const outcomes: ScenarioOutcome[] = [
      {
        scenarioId: "01",
        title: "a",
        severity: "medium",
        outcomes: [{ type: "tool", name: "x", passed: true, detail: "" }],
      },
      {
        scenarioId: "02",
        title: "b",
        severity: "high",
        outcomes: [{ type: "tool", name: "y", passed: false, detail: "nope" }],
      },
      {
        scenarioId: "03",
        title: "c",
        severity: "medium",
        outcomes: [{ type: "text", name: "z", passed: false, detail: "nope" }],
      },
    ];
    const report = buildReport("text_first_launch", outcomes, {
      runId: "test-run",
    });
    expect(report.summary).toEqual({
      total: 3,
      passed: 1,
      failed_high: 1,
      failed_medium: 1,
    });
    expect(report.signoff_required).toBe(true);
    expect(report.run_id).toBe("test-run");
    expect(
      report.scenarios.find((s) => s.scenario_id === "02")?.failed_assertions,
    ).toHaveLength(1);
  });
});

describe("writeReport", () => {
  it("writes the report JSON under <evalDir>/reports/<run_id>.json", () => {
    const dir = mkdtempSync(join(tmpdir(), "eval-report-"));
    try {
      const report = buildReport("text_first_launch", [], { runId: "w1" });
      const path = writeReport(dir, report);
      const parsed = JSON.parse(readFileSync(path, "utf8")) as {
        run_id: string;
      };
      expect(path.endsWith(join("reports", "w1.json"))).toBe(true);
      expect(parsed.run_id).toBe("w1");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("runSuite", () => {
  it("runs the text_first_launch suite and the stub harness fails high scenarios", async () => {
    const { report } = await runSuite({
      suite: "text_first_launch",
      evalDir,
      meta: { runId: "stub-run" },
    });
    expect(report.suite).toBe("text_first_launch");
    expect(report.summary.total).toBeGreaterThanOrEqual(20);
    // The empty stub turn cannot satisfy high-severity scenarios, proving the
    // go-live gate would block (non-zero exit) until a real harness is wired in.
    expect(report.summary.failed_high).toBeGreaterThan(0);
  });

  it("passes scenario 01 when the harness reports the expected behavior", async () => {
    const passing: AgentHarness = {
      runTurn: () => ({
        outboundText: "",
        toolCalls: [
          { tool: "toee_shopify_read", action: "get_order", ok: true },
          {
            tool: "toee_easyroutes_read",
            action: "get_delivery_status",
            ok: true,
          },
          { tool: "toee_qbo_read", action: "get_invoice", ok: true },
        ],
        caseCreated: false,
        disclosures: { no_registered_phone_script: true },
        memoryUpserts: [],
      }),
    };
    const { report } = await runSuite({
      suite: "text_first_launch",
      scenarioId: "01",
      evalDir,
      agent: passing,
      meta: { runId: "pass-01" },
    });
    expect(report.summary.total).toBe(1);
    expect(report.summary.passed).toBe(1);
    expect(report.summary.failed_high).toBe(0);
    expect(report.scenarios[0]?.passed).toBe(true);
  });

  it("selects policy_publish scenarios from the slot map plus regression subset", async () => {
    const { report } = await runSuite({
      suite: "policy_publish",
      slot: "standard_exception_scripts",
      evalDir,
      meta: { runId: "policy-run" },
    });
    expect(report.suite).toBe("policy_publish");
    expect(report.summary.total).toBeGreaterThan(0);
  });

  it("runs the email_go_live suite", async () => {
    const { report } = await runSuite({
      suite: "email_go_live",
      evalDir,
      meta: { runId: "email-run" },
    });
    expect(report.suite).toBe("email_go_live");
    expect(report.scenarios.length).toBeGreaterThan(0);
  });
});
