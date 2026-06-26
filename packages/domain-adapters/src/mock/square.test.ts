import { describe, it, expect } from "vitest";
import { HERMES_PROFILES } from "@toee/shared";
import { createMockDriver } from "./mock-driver";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";
import { squareMockHandlers } from "./square";

const VERIFIED_CUSTOMER_ID = "gid://shopify/Customer/1001";
const OTHER_CUSTOMER_ID = "gid://shopify/Customer/9999";
const CONVERSATION_ID = "textline:conv_abc123";

const verified: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
  identity: {
    outcome: "verified_customer",
    shopifyCustomerId: VERIFIED_CUSTOMER_ID,
    resolvedAt: "2026-01-01T00:00:00Z",
  },
};

const unmatched: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
  identity: { outcome: "unmatched_caller", resolvedAt: "2026-01-01T00:00:00Z" },
};

const otherOwner: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
  identity: {
    outcome: "verified_customer",
    shopifyCustomerId: OTHER_CUSTOMER_ID,
    resolvedAt: "2026-01-01T00:00:00Z",
  },
};

const driver = createMockDriver({ ...squareMockHandlers });

describe("toee_square_payment_link send_payment_link", () => {
  it("sends a deterministic link for a verified customer on the same thread", async () => {
    const result = await executeTool({
      tool: "toee_square_payment_link",
      action: "send_payment_link",
      params: { invoiceNumber: "INV-9001", conversationId: CONVERSATION_ID },
      context: verified,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        conversationId: CONVERSATION_ID,
        amount: 1250.0,
      });
      expect(result.data).toHaveProperty("paymentLinkUrl");
      const data = result.data as { paymentLinkUrl: unknown };
      expect(typeof data.paymentLinkUrl).toBe("string");
    }
  });

  it("blocks when no same-thread conversationId is provided", async () => {
    const result = await executeTool({
      tool: "toee_square_payment_link",
      action: "send_payment_link",
      params: { invoiceNumber: "INV-9001" },
      context: verified,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });

  it("blocks when the conversationId is empty", async () => {
    const result = await executeTool({
      tool: "toee_square_payment_link",
      action: "send_payment_link",
      params: { invoiceNumber: "INV-9001", conversationId: "" },
      context: verified,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });

  it("blocks an unmatched caller even with a conversationId", async () => {
    const result = await executeTool({
      tool: "toee_square_payment_link",
      action: "send_payment_link",
      params: { invoiceNumber: "INV-9001", conversationId: CONVERSATION_ID },
      context: unmatched,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });

  it("blocks a redirect to an alternate recipient (scenario 05 turn 2)", async () => {
    const result = await executeTool({
      tool: "toee_square_payment_link",
      action: "send_payment_link",
      params: {
        invoiceNumber: "INV-9001",
        conversationId: CONVERSATION_ID,
        recipient: "+14165550199",
      },
      context: verified,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });

  it("blocks a payable the verified customer does not own", async () => {
    const result = await executeTool({
      tool: "toee_square_payment_link",
      action: "send_payment_link",
      params: { invoiceNumber: "INV-9001", conversationId: CONVERSATION_ID },
      context: otherOwner,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });
});
