// Mock driver fragment for `toee_identity_lookup` (ADR-0060). Resolves Ingress
// Phone Match / Email Sender Match to a result aligned with the Session Identity
// Snapshot semantics of ADR-0043, and reports Customer Email Link readiness for
// QBO accounting reads. Data is injectable so the Launch Eval fixture loader can
// override the baseline seeded from `eval/mocks/base.yaml`.
import type { MockHandlerRegistry } from "./mock-driver";

// A stored match record keyed by phone or from-address. Absence of a key means
// Unmatched Caller, so only the verified and ambiguous outcomes are stored.
export type IdentityMatchRecord =
  | {
      outcome: "verified_customer";
      shopifyCustomerId: string;
      companyName?: string;
    }
  | {
      outcome: "ambiguous_phone_match";
      shopifyCustomerIds: string[];
    };

// Runtime result returned by match_phone / match_email_sender. `resolvedAt` is
// optional and only present when supplied via params, keeping default output
// deterministic (no Date.now()).
export type IdentityMatchResult =
  | {
      outcome: "verified_customer";
      shopifyCustomerId: string;
      companyName?: string;
      resolvedAt?: string;
    }
  | { outcome: "unmatched_caller"; resolvedAt?: string }
  | {
      outcome: "ambiguous_phone_match";
      shopifyCustomerIds: string[];
      resolvedAt?: string;
    };

export type EmailLinkStatus = "linked" | "unlinked";

export interface IdentityMockData {
  // Phone (E.164) -> match record. Missing phone -> Unmatched Caller.
  phoneMatches: Record<string, IdentityMatchRecord>;
  // Email From address -> match record. Missing address -> Unmatched Caller.
  emailMatches: Record<string, IdentityMatchRecord>;
  // Customer Email Link readiness keyed by Shopify customer id and/or email.
  // Missing key -> "unlinked" (not ready, blocks accounting reads).
  emailLinks: Record<string, EmailLinkStatus>;
}

// Baseline seeded from eval/mocks/base.yaml. verified_customer_a is linked, the
// unmatched phone/email are intentionally absent, and ambiguous matches carry
// both candidate Shopify customer ids.
export const identityBaselineData: IdentityMockData = {
  phoneMatches: {
    "+14165550101": {
      outcome: "verified_customer",
      shopifyCustomerId: "gid://shopify/Customer/1001",
      companyName: "Acme Fleet",
    },
    "+14165550222": {
      outcome: "ambiguous_phone_match",
      shopifyCustomerIds: [
        "gid://shopify/Customer/2001",
        "gid://shopify/Customer/2002",
      ],
    },
  },
  emailMatches: {
    "accounts@acme-fleet.example": {
      outcome: "verified_customer",
      shopifyCustomerId: "gid://shopify/Customer/1001",
      companyName: "Acme Fleet",
    },
    "shared-inbox@acme-fleet.example": {
      outcome: "ambiguous_phone_match",
      shopifyCustomerIds: [
        "gid://shopify/Customer/2001",
        "gid://shopify/Customer/2002",
      ],
    },
  },
  emailLinks: {
    "gid://shopify/Customer/1001": "linked",
    "accounts@acme-fleet.example": "linked",
  },
};

function readString(
  params: Record<string, unknown>,
  ...keys: string[]
): string | undefined {
  for (const key of keys) {
    const value = params[key];
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }
  return undefined;
}

function withResolvedAt(
  result: IdentityMatchResult,
  params: Record<string, unknown>,
): IdentityMatchResult {
  const resolvedAt = params.resolvedAt;
  if (typeof resolvedAt === "string" && resolvedAt.length > 0) {
    return { ...result, resolvedAt };
  }
  return result;
}

function resolveMatch(
  record: IdentityMatchRecord | undefined,
  params: Record<string, unknown>,
): IdentityMatchResult {
  if (record === undefined) {
    return withResolvedAt({ outcome: "unmatched_caller" }, params);
  }
  return withResolvedAt({ ...record }, params);
}

function getEmailLinkStatus(
  data: IdentityMockData,
  params: Record<string, unknown>,
): { status: EmailLinkStatus } {
  const candidates = [
    readString(params, "shopifyCustomerId", "shopify_customer_id"),
    readString(params, "email"),
  ];
  for (const key of candidates) {
    if (key === undefined) {
      continue;
    }
    const status = data.emailLinks[key];
    if (status !== undefined) {
      return { status };
    }
  }
  return { status: "unlinked" };
}

// Builds the registry fragment bound to a specific data set. The Launch Eval
// fixture loader passes per-scenario data; default uses the base.yaml baseline.
export function createIdentityMockHandlers(
  data: IdentityMockData = identityBaselineData,
): MockHandlerRegistry {
  return {
    toee_identity_lookup: {
      match_phone: (params) =>
        resolveMatch(
          data.phoneMatches[readString(params, "phone", "fromPhone", "from_phone") ?? ""],
          params,
        ),
      match_email_sender: (params) =>
        resolveMatch(
          data.emailMatches[readString(params, "fromAddress", "from_address") ?? ""],
          params,
        ),
      get_email_link_status: (params) => getEmailLinkStatus(data, params),
    },
  };
}

export const identityMockHandlers: MockHandlerRegistry =
  createIdentityMockHandlers();
