// Session Identity Snapshot written by Ingress Phone Match before the agent turn
// begins (ADR-0043). The External Customer Service Profile uses only the active
// snapshot for tool authorization.
export type IdentityMatchOutcome =
  | "verified_customer"
  | "unmatched_caller"
  | "ambiguous_phone_match";

export type SessionIdentitySnapshot =
  | {
      outcome: "verified_customer";
      shopifyCustomerId: string;
      resolvedAt: string;
    }
  | {
      outcome: "unmatched_caller";
      resolvedAt: string;
    }
  | {
      outcome: "ambiguous_phone_match";
      shopifyCustomerIds: string[];
      resolvedAt: string;
    };
