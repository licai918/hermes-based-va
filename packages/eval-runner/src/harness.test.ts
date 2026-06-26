import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { executeTool } from "@toee/domain-adapters";
import { describe, expect, it } from "vitest";
import { loadScenario } from "./fixtures";
import {
  createScenarioDriver,
  scenarioExecutionContext,
  stubAgentHarness,
} from "./harness";

const here = dirname(fileURLToPath(import.meta.url));
const evalDir = resolve(here, "../../../eval");

describe("createScenarioDriver", () => {
  it("lets a verified customer read an invoice when the email link is linked (01)", async () => {
    const scenario = loadScenario("text_first_launch", "01", evalDir);
    const driver = createScenarioDriver(scenario.mockContext);
    const result = await executeTool({
      tool: "toee_qbo_read",
      action: "get_invoice",
      params: { invoiceNumber: "INV-9001" },
      context: scenarioExecutionContext(scenario),
      driver,
    });
    expect(result.ok).toBe(true);
  });

  it("blocks the invoice read when the email link override fails (04)", async () => {
    const scenario = loadScenario("text_first_launch", "04", evalDir);
    const driver = createScenarioDriver(scenario.mockContext);
    const result = await executeTool({
      tool: "toee_qbo_read",
      action: "get_invoice",
      params: { invoiceNumber: "INV-9001" },
      context: scenarioExecutionContext(scenario),
      driver,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errorClass).toBe("policy_blocked");
    }
  });

  it("forces a governed failure for an error-marked domain (13 shopify)", async () => {
    const scenario = loadScenario("text_first_launch", "13", evalDir);
    const driver = createScenarioDriver(scenario.mockContext);
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "search_products",
      params: { query: "tire" },
      context: scenarioExecutionContext(scenario),
      driver,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errorClass).toBe("vendor_timeout");
    }
  });
});

describe("stubAgentHarness", () => {
  it("returns a deterministic empty turn result", async () => {
    const scenario = loadScenario("text_first_launch", "01", evalDir);
    const result = await stubAgentHarness.runTurn(scenario);
    expect(result).toEqual({
      outboundText: "",
      toolCalls: [],
      caseCreated: false,
      disclosures: {},
      memoryUpserts: [],
    });
  });
});
