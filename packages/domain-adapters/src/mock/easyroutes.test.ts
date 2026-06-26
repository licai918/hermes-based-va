import { describe, it, expect } from "vitest";
import { HERMES_PROFILES } from "@toee/shared";
import { createMockDriver } from "./mock-driver";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";
import {
  easyroutesMockHandlers,
  createEasyroutesMockHandlers,
} from "./easyroutes";

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

const driver = createMockDriver({ ...easyroutesMockHandlers });

describe("toee_easyroutes_read get_delivery_status", () => {
  it("returns delivery status for the verified owning customer", async () => {
    const result = await executeTool({
      tool: "toee_easyroutes_read",
      action: "get_delivery_status",
      params: { orderNumber: "1042" },
      context: verified,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        orderNumber: "1042",
        status: "in_transit",
      });
    }
  });

  it("blocks an unmatched caller", async () => {
    const result = await executeTool({
      tool: "toee_easyroutes_read",
      action: "get_delivery_status",
      params: { orderNumber: "1042" },
      context: unmatched,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });

  it("blocks a verified customer from a delivery tied to another customer's order", async () => {
    const result = await executeTool({
      tool: "toee_easyroutes_read",
      action: "get_delivery_status",
      params: { orderNumber: "1042" },
      context: otherOwner,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });
});

describe("toee_easyroutes_read get_route_details", () => {
  it("returns route details for the verified owning customer", async () => {
    const result = await executeTool({
      tool: "toee_easyroutes_read",
      action: "get_route_details",
      params: { orderNumber: "1042" },
      context: verified,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({ orderNumber: "1042" });
      expect(result.data).toHaveProperty("stopSequence");
    }
  });

  it("blocks an unmatched caller", async () => {
    const result = await executeTool({
      tool: "toee_easyroutes_read",
      action: "get_route_details",
      params: { orderNumber: "1042" },
      context: unmatched,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });
});

describe("toee_easyroutes_read data injection", () => {
  it("reads deliveries from data injected through the factory", async () => {
    const customDriver = createMockDriver({
      ...createEasyroutesMockHandlers({
        deliveries: [
          {
            orderNumber: "3000",
            shopifyCustomerId: VERIFIED_CUSTOMER_ID,
            status: "delivered",
            stopSequence: 1,
            etaWindow: "2026-01-02T09:00:00Z/2026-01-02T11:00:00Z",
            routeName: "Injected Route",
          },
        ],
      }),
    });

    const result = await executeTool({
      tool: "toee_easyroutes_read",
      action: "get_delivery_status",
      params: { orderNumber: "3000" },
      context: verified,
      driver: customDriver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        orderNumber: "3000",
        status: "delivered",
      });
    }
  });
});
