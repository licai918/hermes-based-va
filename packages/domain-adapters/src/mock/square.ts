// Mock driver for toee_square_payment_link (ADR-0066, ADR-0022). send_payment_link
// requires a Verified Customer and must stay on the current verified Textline
// thread; it is modeled here by a required, non-empty conversationId. Requests
// to redirect to a new contact (eval scenario 05 turn 2) are blocked so the agent
// must open a Follow-up Case instead. Outputs are deterministic — the link is
// derived from the resolved payable, with no external Square call.
import { ToolDriverError } from "../errors";
import type { ToolExecutionContext } from "../tool-gate";
import type { MockHandlerRegistry } from "./mock-driver";

export interface SquarePayable {
  invoiceNumber: string;
  shopifyCustomerId: string;
  amount: number;
}

export interface SquareMockData {
  paymentLinkBaseUrl: string;
  payables: SquarePayable[];
}

// Seeded to match the QBO invoice in eval/mocks/base.yaml (INV-9001, balance
// 1250.0, owned by gid://shopify/Customer/1001) so the payment-link amount lines
// up with the open invoice used in eval scenario 05.
export const squareBaselineData: SquareMockData = {
  paymentLinkBaseUrl: "https://pay.toee.example/square",
  payables: [
    {
      invoiceNumber: "INV-9001",
      shopifyCustomerId: "gid://shopify/Customer/1001",
      amount: 1250.0,
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
      "Payment link requires a verified customer.",
    );
  }
  return identity.shopifyCustomerId;
}

export function createSquareMockHandlers(
  data: SquareMockData = squareBaselineData,
): MockHandlerRegistry {
  return {
    toee_square_payment_link: {
      send_payment_link: (params, context) => {
        const customerId = requireVerifiedCustomerId(context);

        // Same-thread gate (ADR-0022): the link is delivered only in the current
        // authenticated Textline thread, modeled by a required conversationId.
        const conversationId = readString(params, "conversationId");
        if (conversationId === undefined || conversationId.trim() === "") {
          throw new ToolDriverError(
            "policy_blocked",
            "Payment link must be sent in the current verified Textline thread.",
          );
        }

        // A new contact supplied in the message body never changes the send
        // target (ADR-0022 / scenario 05); the agent creates a Follow-up Case.
        const recipient = readString(params, "recipient");
        if (recipient !== undefined && recipient.trim() !== "") {
          throw new ToolDriverError(
            "policy_blocked",
            "Payment link cannot be redirected to an alternate recipient; create a follow-up case instead.",
          );
        }

        const invoiceNumber = readString(params, "invoiceNumber");
        const payable = data.payables.find(
          (candidate) =>
            candidate.invoiceNumber === invoiceNumber &&
            candidate.shopifyCustomerId === customerId,
        );
        if (payable === undefined) {
          throw new ToolDriverError(
            "policy_blocked",
            `No payable ${invoiceNumber ?? "<missing>"} owned by the verified customer.`,
          );
        }

        return {
          paymentLinkUrl: `${data.paymentLinkBaseUrl}/${payable.invoiceNumber}`,
          conversationId,
          amount: payable.amount,
        };
      },
    },
  };
}

export const squareMockHandlers: MockHandlerRegistry =
  createSquareMockHandlers();
