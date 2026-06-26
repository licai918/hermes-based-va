// Mock driver for toee_shopify_read (ADR-0061). Order reads are account-scoped
// and require a Verified Customer who owns the order; product reads are public
// catalog (ADR-0032) and strip account-scoped price/inventory for unmatched
// callers. Outputs are deterministic — no clocks or randomness.
import { ToolDriverError } from "../errors";
import type { ToolExecutionContext } from "../tool-gate";
import type { MockHandlerRegistry } from "./mock-driver";

export interface ShopifyLineItem {
  sku: string;
  title: string;
}

export interface ShopifyOrder {
  orderNumber: string;
  customerId: string;
  lineItems: ShopifyLineItem[];
}

export interface ShopifyProduct {
  productId: string;
  sku: string;
  title: string;
  // Public catalog fields, safe for any caller.
  productUrl: string;
  mediaUrl: string;
  // Account-scoped live facts, only disclosed to Verified Customers.
  price?: string;
  inventory?: number;
}

export interface ShopifyMockData {
  orders: ShopifyOrder[];
  products: ShopifyProduct[];
}

// Seeded from eval/mocks/base.yaml (shopify.orders.recent_order_a). The product
// catalog has no base.yaml slice, so one deterministic product is seeded to back
// search_products / get_product, aligned to the order's line item SKU.
export const shopifyBaselineData: ShopifyMockData = {
  orders: [
    {
      orderNumber: "1042",
      customerId: "gid://shopify/Customer/1001",
      lineItems: [{ sku: "TIRE-225-60R16", title: "All-Season 225/60R16" }],
    },
  ],
  products: [
    {
      productId: "gid://shopify/Product/7001",
      sku: "TIRE-225-60R16",
      title: "All-Season 225/60R16",
      productUrl: "https://shop.toee.example/products/all-season-225-60r16",
      mediaUrl: "https://cdn.toee.example/products/all-season-225-60r16.jpg",
      price: "189.99",
      inventory: 24,
    },
  ],
};

function readString(
  params: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = params[key];
  return typeof value === "string" ? value : undefined;
}

// Account-scoped Shopify reads require a Verified Customer (ADR-0061). Unmatched
// and ambiguous sessions never receive order facts.
function requireVerifiedCustomerId(context: ToolExecutionContext): string {
  const identity = context.identity;
  if (identity === undefined || identity.outcome !== "verified_customer") {
    throw new ToolDriverError(
      "policy_blocked",
      "Account-scoped Shopify read requires a verified customer.",
    );
  }
  return identity.shopifyCustomerId;
}

function toPublicProduct(product: ShopifyProduct): Record<string, unknown> {
  return {
    productId: product.productId,
    sku: product.sku,
    title: product.title,
    productUrl: product.productUrl,
    mediaUrl: product.mediaUrl,
  };
}

function toVerifiedProduct(product: ShopifyProduct): Record<string, unknown> {
  return {
    ...toPublicProduct(product),
    price: product.price,
    inventory: product.inventory,
  };
}

export function createShopifyMockHandlers(
  data: ShopifyMockData = shopifyBaselineData,
): MockHandlerRegistry {
  return {
    toee_shopify_read: {
      get_order: (params, context) => {
        const customerId = requireVerifiedCustomerId(context);
        const orderNumber = readString(params, "orderNumber");
        const order = data.orders.find(
          (candidate) =>
            candidate.orderNumber === orderNumber &&
            candidate.customerId === customerId,
        );
        if (order === undefined) {
          throw new ToolDriverError(
            "policy_blocked",
            `No order ${orderNumber ?? "<missing>"} owned by the verified customer.`,
          );
        }
        return { ...order };
      },

      list_customer_orders: (_params, context) => {
        const customerId = requireVerifiedCustomerId(context);
        return data.orders
          .filter((order) => order.customerId === customerId)
          .map((order) => ({ ...order }));
      },

      search_products: (params) => {
        const query = readString(params, "query")?.toLowerCase();
        const matches =
          query === undefined || query === ""
            ? data.products
            : data.products.filter(
                (product) =>
                  product.title.toLowerCase().includes(query) ||
                  product.sku.toLowerCase().includes(query),
              );
        return matches.map(toPublicProduct);
      },

      get_product: (params, context) => {
        const productId = readString(params, "productId");
        const sku = readString(params, "sku");
        const product = data.products.find(
          (candidate) =>
            candidate.productId === productId || candidate.sku === sku,
        );
        if (product === undefined) {
          throw new ToolDriverError(
            "unexpected_error",
            `Product ${productId ?? sku ?? "<missing>"} not found.`,
          );
        }
        const isVerified = context.identity?.outcome === "verified_customer";
        return isVerified
          ? toVerifiedProduct(product)
          : toPublicProduct(product);
      },
    },
  };
}

export const shopifyMockHandlers: MockHandlerRegistry =
  createShopifyMockHandlers();
