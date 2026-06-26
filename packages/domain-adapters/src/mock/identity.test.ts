import { describe, it, expect } from "vitest";
import { HERMES_PROFILES } from "@toee/shared";
import { createMockDriver } from "./mock-driver";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";
import {
  identityMockHandlers,
  createIdentityMockHandlers,
  type IdentityMockData,
} from "./identity";

const context: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
};

function baselineDriver() {
  return createMockDriver({ ...identityMockHandlers });
}

describe("toee_identity_lookup mock — match_phone", () => {
  it("resolves a verified customer with company name", async () => {
    const result = await executeTool({
      tool: "toee_identity_lookup",
      action: "match_phone",
      params: { phone: "+14165550101" },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({
        outcome: "verified_customer",
        shopifyCustomerId: "gid://shopify/Customer/1001",
        companyName: "Acme Fleet",
      });
    }
  });

  it("resolves an unmatched caller", async () => {
    const result = await executeTool({
      tool: "toee_identity_lookup",
      action: "match_phone",
      params: { phone: "+14165550999" },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ outcome: "unmatched_caller" });
    }
  });

  it("resolves an ambiguous phone match", async () => {
    const result = await executeTool({
      tool: "toee_identity_lookup",
      action: "match_phone",
      params: { phone: "+14165550222" },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({
        outcome: "ambiguous_phone_match",
        shopifyCustomerIds: [
          "gid://shopify/Customer/2001",
          "gid://shopify/Customer/2002",
        ],
      });
    }
  });

  it("treats an unknown/blank phone as an unmatched caller", async () => {
    const result = await executeTool({
      tool: "toee_identity_lookup",
      action: "match_phone",
      params: {},
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ outcome: "unmatched_caller" });
    }
  });

  it("omits resolvedAt by default but echoes a provided resolvedAt", async () => {
    const withTimestamp = await executeTool({
      tool: "toee_identity_lookup",
      action: "match_phone",
      params: { phone: "+14165550101", resolvedAt: "2026-01-01T00:00:00.000Z" },
      context,
      driver: baselineDriver(),
    });

    expect(withTimestamp.ok).toBe(true);
    if (withTimestamp.ok) {
      expect(withTimestamp.data).toEqual({
        outcome: "verified_customer",
        shopifyCustomerId: "gid://shopify/Customer/1001",
        companyName: "Acme Fleet",
        resolvedAt: "2026-01-01T00:00:00.000Z",
      });
    }
  });
});

describe("toee_identity_lookup mock — match_email_sender", () => {
  it("resolves a verified sender", async () => {
    const result = await executeTool({
      tool: "toee_identity_lookup",
      action: "match_email_sender",
      params: { fromAddress: "accounts@acme-fleet.example" },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({
        outcome: "verified_customer",
        shopifyCustomerId: "gid://shopify/Customer/1001",
        companyName: "Acme Fleet",
      });
    }
  });

  it("resolves an unmatched sender", async () => {
    const result = await executeTool({
      tool: "toee_identity_lookup",
      action: "match_email_sender",
      params: { fromAddress: "unknown.sender@example.com" },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ outcome: "unmatched_caller" });
    }
  });

  it("resolves an ambiguous sender (parallels phone, ADR-0053)", async () => {
    const result = await executeTool({
      tool: "toee_identity_lookup",
      action: "match_email_sender",
      params: { from_address: "shared-inbox@acme-fleet.example" },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({
        outcome: "ambiguous_phone_match",
        shopifyCustomerIds: [
          "gid://shopify/Customer/2001",
          "gid://shopify/Customer/2002",
        ],
      });
    }
  });
});

describe("toee_identity_lookup mock — get_email_link_status", () => {
  it("returns linked for a linked Shopify customer id", async () => {
    const result = await executeTool({
      tool: "toee_identity_lookup",
      action: "get_email_link_status",
      params: { shopifyCustomerId: "gid://shopify/Customer/1001" },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ status: "linked" });
    }
  });

  it("returns linked when keyed by the linked email", async () => {
    const result = await executeTool({
      tool: "toee_identity_lookup",
      action: "get_email_link_status",
      params: { email: "accounts@acme-fleet.example" },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ status: "linked" });
    }
  });

  it("returns unlinked for an unknown customer", async () => {
    const result = await executeTool({
      tool: "toee_identity_lookup",
      action: "get_email_link_status",
      params: { shopifyCustomerId: "gid://shopify/Customer/9999" },
      context,
      driver: baselineDriver(),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ status: "unlinked" });
    }
  });
});

describe("toee_identity_lookup mock — injectable data", () => {
  it("honors overridden fixture data via the factory", async () => {
    const overrides: IdentityMockData = {
      phoneMatches: {
        "+15555550000": {
          outcome: "verified_customer",
          shopifyCustomerId: "gid://shopify/Customer/7777",
        },
      },
      emailMatches: {},
      emailLinks: { "gid://shopify/Customer/7777": "unlinked" },
    };
    const driver = createMockDriver({
      ...createIdentityMockHandlers(overrides),
    });

    const match = await executeTool({
      tool: "toee_identity_lookup",
      action: "match_phone",
      params: { phone: "+15555550000" },
      context,
      driver,
    });

    expect(match.ok).toBe(true);
    if (match.ok) {
      expect(match.data).toEqual({
        outcome: "verified_customer",
        shopifyCustomerId: "gid://shopify/Customer/7777",
      });
    }

    const link = await executeTool({
      tool: "toee_identity_lookup",
      action: "get_email_link_status",
      params: { shopifyCustomerId: "gid://shopify/Customer/7777" },
      context,
      driver,
    });

    expect(link.ok).toBe(true);
    if (link.ok) {
      expect(link.data).toEqual({ status: "unlinked" });
    }
  });
});
