// Mock driver for toee_easyroutes_read (ADR-0063). Both actions are
// account-scoped: they require a Verified Customer and an order reference tied
// to that customer. Unmatched callers cannot call either action. Outputs are
// deterministic.
import { ToolDriverError } from "../errors";
import type { ToolExecutionContext } from "../tool-gate";
import type { MockHandlerRegistry } from "./mock-driver";

export interface EasyRoutesDelivery {
  orderNumber: string;
  shopifyCustomerId: string;
  status: string;
  stopSequence: number;
  etaWindow: string;
  routeName: string;
}

export interface EasyRoutesMockData {
  deliveries: EasyRoutesDelivery[];
}

// Seeded from eval/mocks/base.yaml (easyroutes.deliveries.delivery_a). The
// delivery is tied to order 1042, which Shopify base data owns under
// gid://shopify/Customer/1001, so the delivery carries that owner link here.
export const easyroutesBaselineData: EasyRoutesMockData = {
  deliveries: [
    {
      orderNumber: "1042",
      shopifyCustomerId: "gid://shopify/Customer/1001",
      status: "in_transit",
      stopSequence: 4,
      etaWindow: "2026-01-02T14:00:00Z/2026-01-02T16:00:00Z",
      routeName: "Route 7 - GTA West",
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

function requireVerifiedCustomerId(context: ToolExecutionContext): string {
  const identity = context.identity;
  if (identity === undefined || identity.outcome !== "verified_customer") {
    throw new ToolDriverError(
      "policy_blocked",
      "EasyRoutes read requires a verified customer.",
    );
  }
  return identity.shopifyCustomerId;
}

// Resolve a delivery the verified customer owns. A missing or non-owned order
// reference is a governed policy block, never fabricated delivery facts.
function findOwnedDelivery(
  data: EasyRoutesMockData,
  customerId: string,
  orderNumber: string | undefined,
): EasyRoutesDelivery {
  const delivery = data.deliveries.find(
    (candidate) =>
      candidate.orderNumber === orderNumber &&
      candidate.shopifyCustomerId === customerId,
  );
  if (delivery === undefined) {
    throw new ToolDriverError(
      "policy_blocked",
      `No delivery for order ${orderNumber ?? "<missing>"} owned by the verified customer.`,
    );
  }
  return delivery;
}

export function createEasyroutesMockHandlers(
  data: EasyRoutesMockData = easyroutesBaselineData,
): MockHandlerRegistry {
  return {
    toee_easyroutes_read: {
      get_delivery_status: (params, context) => {
        const customerId = requireVerifiedCustomerId(context);
        const delivery = findOwnedDelivery(
          data,
          customerId,
          readString(params, "orderNumber"),
        );
        return {
          orderNumber: delivery.orderNumber,
          status: delivery.status,
        };
      },

      get_route_details: (params, context) => {
        const customerId = requireVerifiedCustomerId(context);
        const delivery = findOwnedDelivery(
          data,
          customerId,
          readString(params, "orderNumber"),
        );
        return {
          orderNumber: delivery.orderNumber,
          stopSequence: delivery.stopSequence,
          etaWindow: delivery.etaWindow,
          routeName: delivery.routeName,
        };
      },
    },
  };
}

export const easyroutesMockHandlers: MockHandlerRegistry =
  createEasyroutesMockHandlers();
