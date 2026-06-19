import { describe, it, expect } from "vitest";
import { HERMES_PROFILES } from "@toee/shared";
import { createMockDriver } from "./mock-driver";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";
import {
  shopifyMockHandlers,
  createShopifyMockHandlers,
  shopifyBaselineData,
} from "./shopify";

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

const ambiguous: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
  identity: {
    outcome: "ambiguous_phone_match",
    shopifyCustomerIds: [OTHER_CUSTOMER_ID, "gid://shopify/Customer/2002"],
    resolvedAt: "2026-01-01T00:00:00Z",
  },
};

const otherOwner: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
  identity: {
    outcome: "verified_customer",
    shopifyCustomerId: OTHER_CUSTOMER_ID,
    resolvedAt: "2026-01-01T00:00:00Z",
  },
};

const driver = createMockDriver({ ...shopifyMockHandlers });

function firstBaselineProductId(): string {
  const product = shopifyBaselineData.products[0];
  if (!product) throw new Error("expected a baseline product fixture");
  return product.productId;
}

describe("toee_shopify_read get_order", () => {
  it("returns the order for the verified owning customer", async () => {
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "get_order",
      params: { orderNumber: "1042" },
      context: verified,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        orderNumber: "1042",
        customerId: VERIFIED_CUSTOMER_ID,
      });
    }
  });

  it("blocks an unmatched caller from account-scoped order reads", async () => {
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "get_order",
      params: { orderNumber: "1042" },
      context: unmatched,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });

  it("blocks an ambiguous phone match from account-scoped order reads", async () => {
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "get_order",
      params: { orderNumber: "1042" },
      context: ambiguous,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });

  it("blocks a verified customer from reading an order they do not own", async () => {
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "get_order",
      params: { orderNumber: "1042" },
      context: otherOwner,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });
});

describe("toee_shopify_read list_customer_orders", () => {
  it("returns only the verified customer's orders", async () => {
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "list_customer_orders",
      context: verified,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual([
        expect.objectContaining({
          orderNumber: "1042",
          customerId: VERIFIED_CUSTOMER_ID,
        }),
      ]);
    }
  });

  it("blocks an unmatched caller", async () => {
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "list_customer_orders",
      context: unmatched,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorClass).toBe("policy_blocked");
  });
});

describe("toee_shopify_read public catalog", () => {
  it("lets an unmatched caller search products with public fields only", async () => {
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "search_products",
      params: { query: "225" },
      context: unmatched,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      const products = result.data as Array<Record<string, unknown>>;
      expect(products.length).toBeGreaterThan(0);
      for (const product of products) {
        expect(product).not.toHaveProperty("price");
        expect(product).not.toHaveProperty("inventory");
        expect(product).toHaveProperty("productUrl");
      }
    }
  });

  it("returns media/link only for an unmatched get_product", async () => {
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "get_product",
      params: { productId: firstBaselineProductId() },
      context: unmatched,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).not.toHaveProperty("price");
      expect(result.data).not.toHaveProperty("inventory");
      expect(result.data).toHaveProperty("productUrl");
      expect(result.data).toHaveProperty("mediaUrl");
    }
  });

  it("includes live price and inventory for a verified get_product", async () => {
    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "get_product",
      params: { productId: firstBaselineProductId() },
      context: verified,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toHaveProperty("price");
      expect(result.data).toHaveProperty("inventory");
    }
  });
});

describe("toee_shopify_read data injection", () => {
  it("reads orders from data injected through the factory", async () => {
    const customDriver = createMockDriver({
      ...createShopifyMockHandlers({
        orders: [
          {
            orderNumber: "2000",
            customerId: VERIFIED_CUSTOMER_ID,
            lineItems: [{ sku: "TIRE-TEST", title: "Injected Tire" }],
          },
        ],
        products: [],
      }),
    });

    const result = await executeTool({
      tool: "toee_shopify_read",
      action: "get_order",
      params: { orderNumber: "2000" },
      context: verified,
      driver: customDriver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({ orderNumber: "2000" });
    }
  });
});
