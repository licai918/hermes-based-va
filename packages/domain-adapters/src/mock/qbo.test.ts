import { describe, it, expect } from "vitest";
import { HERMES_PROFILES } from "@toee/shared";
import { createMockDriver } from "./mock-driver";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";
import { qboMockHandlers, createQboMockHandlers, qboBaselineData } from "./qbo";

const VERIFIED_CUSTOMER_ID = "gid://shopify/Customer/1001";
const OTHER_CUSTOMER_ID = "gid://shopify/Customer/9999";

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

const driver = createMockDriver({ ...qboMockHandlers });

describe("toee_qbo_read get_invoice", () => {
  it("returns the invoice for a verified, email-linked customer", async () => {
    const result = await executeTool({
      tool: "toee_qbo_read",
      action: "get_invoice",
      params: { invoiceNumber: "INV-9001" },
      context: verified,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        invoiceNumber: "INV-9001",
        balance: 1250.0,
      });
    }
  });

  it("blocks an unmatched caller", async () => {
    const result = await executeTool({
      tool: "toee_qbo_read",
      action: "get_invoice",
      params: { invoiceNumber: "INV-9001" },
      context: unmatched,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });

  it("blocks a verified customer whose email link is not linked", async () => {
    const unlinkedDriver = createMockDriver({
      ...createQboMockHandlers({
        ...qboBaselineData,
        emailLinks: { [VERIFIED_CUSTOMER_ID]: "unlinked" },
      }),
    });

    const result = await executeTool({
      tool: "toee_qbo_read",
      action: "get_invoice",
      params: { invoiceNumber: "INV-9001" },
      context: verified,
      driver: unlinkedDriver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });

  it("blocks a verified customer reading an invoice they do not own", async () => {
    // Grant the other customer a successful email link so only ownership can fail.
    const ownershipDriver = createMockDriver({
      ...createQboMockHandlers({
        ...qboBaselineData,
        emailLinks: {
          ...qboBaselineData.emailLinks,
          [OTHER_CUSTOMER_ID]: "linked",
        },
      }),
    });

    const result = await executeTool({
      tool: "toee_qbo_read",
      action: "get_invoice",
      params: { invoiceNumber: "INV-9001" },
      context: otherOwner,
      driver: ownershipDriver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });
});

describe("toee_qbo_read list_customer_invoices", () => {
  it("returns the verified customer's invoices", async () => {
    const result = await executeTool({
      tool: "toee_qbo_read",
      action: "list_customer_invoices",
      context: verified,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual([
        expect.objectContaining({ invoiceNumber: "INV-9001" }),
      ]);
    }
  });

  it("blocks an unmatched caller", async () => {
    const result = await executeTool({
      tool: "toee_qbo_read",
      action: "list_customer_invoices",
      context: unmatched,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });
});

describe("toee_qbo_read get_ar_summary", () => {
  it("returns an AR summary for the verified customer", async () => {
    const result = await executeTool({
      tool: "toee_qbo_read",
      action: "get_ar_summary",
      context: verified,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        shopifyCustomerId: VERIFIED_CUSTOMER_ID,
        totalBalance: 1250.0,
        openInvoiceCount: 1,
      });
    }
  });

  it("blocks an unmatched caller", async () => {
    const result = await executeTool({
      tool: "toee_qbo_read",
      action: "get_ar_summary",
      context: unmatched,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });
});
