import { describe, it, expect } from "vitest";
import { HERMES_PROFILES, type ToolName } from "@toee/shared";
import { executeTool } from "./execute-tool";
import type { ToolDriver, ToolAuditRecord } from "./execute-tool";
import type { ToolExecutionContext, ToolGate } from "./tool-gate";
import { ToolDriverError } from "./errors";

const context: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
};

class FakeDriver implements ToolDriver {
  readonly kind = "mock" as const;
  calls: Array<{ tool: ToolName; action: string }> = [];

  constructor(
    private readonly behavior: () => Promise<unknown> = async () => ({
      handled: true,
    }),
  ) {}

  async execute(request: {
    tool: ToolName;
    action: string;
    params: Record<string, unknown>;
  }): Promise<unknown> {
    this.calls.push({ tool: request.tool, action: request.action });
    return this.behavior();
  }
}

describe("executeTool dispatch", () => {
  it("returns a governed failure for an unknown tool and never calls the driver", async () => {
    const driver = new FakeDriver();
    const result = await executeTool({
      tool: "toee_business_write",
      action: "create_order",
      context,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errorClass).toBe("unknown_tool");
    }
    expect(driver.calls).toHaveLength(0);
  });

  it("returns a governed failure for an action that is not in the tool's enum", async () => {
    const driver = new FakeDriver();
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "create_case",
      context,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errorClass).toBe("unknown_action");
    }
    expect(driver.calls).toHaveLength(0);
  });

  it("lets the Tool Gate block an action before driver invocation", async () => {
    const driver = new FakeDriver();
    const denyPaymentLink: ToolGate = (request) =>
      request.tool === "toee_square_payment_link"
        ? {
            allow: false,
            errorClass: "policy_blocked",
            message: "Payment link requires a verified customer.",
          }
        : { allow: true };

    const result = await executeTool({
      tool: "toee_square_payment_link",
      action: "send_payment_link",
      context,
      driver,
      gate: denyPaymentLink,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errorClass).toBe("policy_blocked");
    }
    expect(driver.calls).toHaveLength(0);
  });

  it("invokes the driver and returns data on the happy path", async () => {
    const driver = new FakeDriver(async () => ({ messageId: "m_1" }));
    const records: ToolAuditRecord[] = [];

    const result = await executeTool({
      tool: "toee_textline_reply",
      action: "send_message",
      params: { body: "hi" },
      context,
      driver,
      audit: (record) => records.push(record),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ messageId: "m_1" });
    }
    expect(driver.calls).toEqual([
      { tool: "toee_textline_reply", action: "send_message" },
    ]);
    expect(records).toHaveLength(1);
    expect(records[0]).toMatchObject({
      tool: "toee_textline_reply",
      action: "send_message",
      driver: "mock",
      outcome: "ok",
    });
  });

  it("maps a driver failure to a governed Tool Unavailable Response with error class", async () => {
    const driver = new FakeDriver(async () => {
      throw new ToolDriverError("auth_expired", "connected account expired");
    });
    const records: ToolAuditRecord[] = [];

    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "get_order",
      context,
      driver,
      audit: (record) => records.push(record),
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errorClass).toBe("auth_expired");
      expect(result.message).not.toContain("connected account expired");
    }
    expect(records).toEqual([
      expect.objectContaining({
        tool: "toee_shopify_read",
        action: "get_order",
        outcome: "unavailable",
        errorClass: "auth_expired",
      }),
    ]);
  });
});
