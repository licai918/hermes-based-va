// Mock driver for toee_qbo_read (ADR-0062). Every action requires a Verified
// Customer AND a successful Customer Email Link between the Shopify Customer and
// the QBO Customer; on email-link failure the adapter returns a governed failure
// rather than partial accounting disclosure. Outputs are deterministic.
import { ToolDriverError } from "../errors";
import type { ToolExecutionContext } from "../tool-gate";
import type { MockHandlerRegistry } from "./mock-driver";

export type QboEmailLinkStatus = "linked" | "unlinked";

export interface QboInvoice {
  invoiceNumber: string;
  shopifyCustomerId: string;
  customerEmail: string;
  balance: number;
}

export interface QboMockData {
  // Email-link status keyed by matched Shopify Customer id.
  emailLinks: Record<string, QboEmailLinkStatus>;
  invoices: QboInvoice[];
}

// Seeded from eval/mocks/base.yaml. The base file keys the email link by the
// `verified_customer_a` identity preset, whose shopify_customer_id is
// gid://shopify/Customer/1001, so the link is keyed by that id here.
export const qboBaselineData: QboMockData = {
  emailLinks: { "gid://shopify/Customer/1001": "linked" },
  invoices: [
    {
      invoiceNumber: "INV-9001",
      shopifyCustomerId: "gid://shopify/Customer/1001",
      customerEmail: "accounts@acme-fleet.example",
      balance: 1250.0,
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
      "QBO read requires a verified customer.",
    );
  }
  return identity.shopifyCustomerId;
}

// Customer Email Link gate (ADR-0062): block when the matched customer is not
// linked to a QBO Customer instead of leaking partial accounting facts.
function requireEmailLink(customerId: string, data: QboMockData): void {
  if (data.emailLinks[customerId] !== "linked") {
    throw new ToolDriverError(
      "policy_blocked",
      "QBO read requires a successful customer email link.",
    );
  }
}

export function createQboMockHandlers(
  data: QboMockData = qboBaselineData,
): MockHandlerRegistry {
  return {
    toee_qbo_read: {
      get_invoice: (params, context) => {
        const customerId = requireVerifiedCustomerId(context);
        requireEmailLink(customerId, data);
        const invoiceNumber = readString(params, "invoiceNumber");
        const invoice = data.invoices.find(
          (candidate) =>
            candidate.invoiceNumber === invoiceNumber &&
            candidate.shopifyCustomerId === customerId,
        );
        if (invoice === undefined) {
          throw new ToolDriverError(
            "policy_blocked",
            `No invoice ${invoiceNumber ?? "<missing>"} owned by the verified customer.`,
          );
        }
        return { ...invoice };
      },

      list_customer_invoices: (_params, context) => {
        const customerId = requireVerifiedCustomerId(context);
        requireEmailLink(customerId, data);
        return data.invoices
          .filter((invoice) => invoice.shopifyCustomerId === customerId)
          .map((invoice) => ({ ...invoice }));
      },

      get_ar_summary: (_params, context) => {
        const customerId = requireVerifiedCustomerId(context);
        requireEmailLink(customerId, data);
        const owned = data.invoices.filter(
          (invoice) => invoice.shopifyCustomerId === customerId,
        );
        const totalBalance = owned.reduce(
          (sum, invoice) => sum + invoice.balance,
          0,
        );
        return {
          shopifyCustomerId: customerId,
          openInvoiceCount: owned.length,
          totalBalance,
        };
      },
    },
  };
}

export const qboMockHandlers: MockHandlerRegistry = createQboMockHandlers();
