import { describe, it, expect } from "vitest";
import { HERMES_PROFILES } from "@toee/shared";
import { createMockDriver } from "./mock-driver";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";
import {
  caseMockHandlers,
  createCaseMockHandlers,
  type CaseMockData,
} from "./case";

const context: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
};

function baselineDriver() {
  return createMockDriver({ ...caseMockHandlers });
}

describe("toee_case mock — create_case", () => {
  it("returns a deterministic open case echoing the contact reason", async () => {
    const result = await executeTool({
      tool: "toee_case",
      action: "create_case",
      params: {
        contact_reason: "billing_question",
        summary: "Customer asked about invoice INV-9001",
        channel_thread_id: "conv_1",
      },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        status: "open",
        contactReason: "billing_question",
        channelThreadId: "conv_1",
      });
      const created = result.data as { caseId: string };
      expect(typeof created.caseId).toBe("string");
      expect(created.caseId.length).toBeGreaterThan(0);
    }
  });

  it("produces the same caseId for identical params (deterministic)", async () => {
    const params = {
      contact_reason: "delivery_status",
      channel_thread_id: "conv_42",
    };
    const first = await executeTool({
      tool: "toee_case",
      action: "create_case",
      params,
      context,
      driver: baselineDriver(),
    });
    const second = await executeTool({
      tool: "toee_case",
      action: "create_case",
      params,
      context,
      driver: baselineDriver(),
    });

    expect(first.ok && second.ok).toBe(true);
    if (first.ok && second.ok) {
      expect(first.data).toEqual(second.data);
    }
  });

  it("produces different caseIds for different threads", async () => {
    const first = await executeTool({
      tool: "toee_case",
      action: "create_case",
      params: { contact_reason: "delivery_status", channel_thread_id: "conv_a" },
      context,
      driver: baselineDriver(),
    });
    const second = await executeTool({
      tool: "toee_case",
      action: "create_case",
      params: { contact_reason: "delivery_status", channel_thread_id: "conv_b" },
      context,
      driver: baselineDriver(),
    });

    expect(first.ok && second.ok).toBe(true);
    if (first.ok && second.ok) {
      const a = first.data as { caseId: string };
      const b = second.data as { caseId: string };
      expect(a.caseId).not.toBe(b.caseId);
    }
  });

  it("applies an injected default urgency when none is supplied", async () => {
    const data: CaseMockData = {
      caseIdPrefix: "case",
      defaultStatus: "open",
      defaultUrgency: "urgent",
    };
    const driver = createMockDriver({ ...createCaseMockHandlers(data) });

    const result = await executeTool({
      tool: "toee_case",
      action: "create_case",
      params: { contact_reason: "government_inquiry", channel_thread_id: "conv_g" },
      context,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        status: "open",
        urgency: "urgent",
        contactReason: "government_inquiry",
      });
    }
  });
});

describe("toee_case mock — update_case", () => {
  it("echoes the updated urgency and contact reason for the given case", async () => {
    const result = await executeTool({
      tool: "toee_case",
      action: "update_case",
      params: {
        case_id: "case_abc123",
        urgency: "high",
        contact_reason: "delivery_escalation",
      },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        caseId: "case_abc123",
        status: "open",
        urgency: "high",
        contactReason: "delivery_escalation",
      });
    }
  });
});
