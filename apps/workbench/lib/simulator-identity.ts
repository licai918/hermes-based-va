// Identity presets for the Conversation Simulator (0.0.3 S04, FR-9/FR-13).
//
// Presets are curated PHONE VALUES only -- picking one fills the "From phone"
// field exactly like typing it in by hand. They never fabricate an identity
// server-side; the real gateway webhook still runs the production Ingress
// Phone Match (hermes/toee_hermes/gateway/ingress.py) against whatever
// driver INTEGRATION_DRIVER selects.
//
// Provenance: local dev defaults to INTEGRATION_DRIVER=mock (ADR-0137,
// .env.example), so the driver actually hit is the default mock identity
// registry (hermes/toee_hermes/drivers/mock/identity.py
// `identity_baseline_data`, wired in via `create_all_mock_handlers`). Its
// `phone_matches` table is the source of truth for these two fixed numbers:
//   +14165550101 -> outcome "verified_customer" (Acme Fleet)
//   +14165550222 -> outcome "ambiguous_phone_match" (two candidate ids)
// Any other number (nothing in that table) resolves "unmatched_caller", so
// "unknown caller" just needs a number that was never seeded -- a fresh
// random +1555 number every time, so repeated runs never collide with a
// prior identity or thread.
//
// hermes-runtime/migrations/0005_dev_bootstrap.sql seeds pre-existing case
// rows under different numbers (+15554471471, +15552221000), but those are
// Workbench case history, not the identity-lookup table -- sending a NEW
// simulated message from them would still hit the mock driver above and
// come back unmatched. Not used here for that reason.
//
// S18/FR-11 adds the email-shaped sibling below (EMAIL_PRESETS /
// resolvePresetEmail), seeded from the same mock driver's `email_matches`
// table -- kept as a separate preset list rather than reusing this one
// directly, since a phone value and an email address are never
// interchangeable identity shapes.

export type IdentityPresetId = "verified" | "ambiguous" | "unknown";

export interface IdentityPreset {
  id: IdentityPresetId;
  label: string;
  /** Fixed phone for presets seeded in the mock identity driver; absent for "unknown", which generates fresh. */
  phone?: string;
}

/** The phone the mock identity driver seeds as `verified_customer` (Acme Fleet). */
export const SEEDED_VERIFIED_PHONE = "+14165550101";

// PAC-6 test-data precondition (0.0.4 S12). Everything above describes the MOCK
// driver. The moment INTEGRATION_DRIVER=composio, ingress phone match runs
// against the LIVE Shopify store, where +14165550101 is nobody -- the "verified"
// preset resolves `unmatched_caller` and the PAC drill has no verified path to
// run. Point this at a DEDICATED TEST CUSTOMER created in the live store (with a
// test order + invoice), never a real customer's number:
//
//   NEXT_PUBLIC_SIM_VERIFIED_PHONE=+1...   (apps/workbench/.env.local)
//
// Left unset -- the local-dev default -- the seeded mock number is used and
// nothing changes. It is NEXT_PUBLIC_ because the Simulator is a client
// component; the value is a test phone number, not a credential.
export function resolveVerifiedPhone(configured?: string): string {
  return configured?.trim() || SEEDED_VERIFIED_PHONE;
}

const VERIFIED_PHONE = resolveVerifiedPhone(process.env.NEXT_PUBLIC_SIM_VERIFIED_PHONE);

export const IDENTITY_PRESETS: readonly IdentityPreset[] = [
  {
    id: "verified",
    // The label names the data source, because which one is live decides whether
    // a failed PAC run means "the tool is broken" or "the test customer is missing".
    label:
      VERIFIED_PHONE === SEEDED_VERIFIED_PHONE
        ? "Verified customer (seeded)"
        : "Verified customer (live test entity)",
    phone: VERIFIED_PHONE,
  },
  { id: "ambiguous", label: "Ambiguous match (seeded)", phone: "+14165550222" },
  { id: "unknown", label: "Unknown caller (fresh number)" },
];

// S05 "link identity" (FR-13): the fixed target the control links the current
// simulated channel identity to. The SAME Shopify customer the "verified"
// preset's seeded phone (+14165550101) already resolves to, so linking a
// DIFFERENT (e.g. "unknown") channel identity to this id demonstrates FR-19's
// cross-channel continuity -- two channel identities becoming linked to each
// other reduces to both resolving to this one customer (see
// hermes-runtime/hermes_runtime/datastore/handlers/identity.py's
// _link_identity docstring).
export const LINK_IDENTITY_TARGET = {
  shopifyCustomerId: "gid://shopify/Customer/1001",
  companyName: "Acme Fleet",
} as const;

// ponytail: a 7-digit random suffix gives a 1-in-10M collision chance per
// pair of picks -- plenty for a manual test surface. Upgrade to a counter or
// UUID-derived suffix if PAC runs ever hit real collisions.
export function generateUnknownCallerPhone(random: () => number = Math.random): string {
  const digits = Array.from({ length: 7 }, () => Math.floor(random() * 10)).join("");
  return `+1555${digits}`;
}

export function resolvePresetPhone(
  presetId: IdentityPresetId,
  random?: () => number,
): string {
  const preset = IDENTITY_PRESETS.find((p) => p.id === presetId);
  return preset?.phone ?? generateUnknownCallerPhone(random);
}

// Email identity presets (0.0.3 S18, FR-11). Same shape as the phone presets
// above -- curated ADDRESS values only, filling the email composer's "From
// address" field exactly like typing it in. NFR-4: simulated addresses only,
// never a real inbox.
//
// Provenance: the seeded addresses come from the SAME mock identity registry
// as the phone presets (hermes/toee_hermes/drivers/mock/identity.py
// `identity_baseline_data.email_matches`):
//   accounts@acme-fleet.example      -> outcome "verified_customer" (Acme Fleet)
//   shared-inbox@acme-fleet.example  -> outcome "ambiguous_phone_match" (two candidate ids)
// Any other address resolves "unmatched_caller", so "unknown caller" just
// needs an address that was never seeded -- a fresh random one every time.

export interface EmailPreset {
  id: IdentityPresetId;
  label: string;
  /** Fixed address for presets seeded in the mock identity driver; absent for "unknown", which generates fresh. */
  address?: string;
}

export const EMAIL_PRESETS: readonly EmailPreset[] = [
  { id: "verified", label: "Verified customer (seeded)", address: "accounts@acme-fleet.example" },
  {
    id: "ambiguous",
    label: "Ambiguous match (seeded)",
    address: "shared-inbox@acme-fleet.example",
  },
  { id: "unknown", label: "Unknown caller (fresh address)" },
];

// ponytail: a 7-digit random suffix gives a 1-in-10M collision chance per pair
// of picks -- plenty for a manual test surface, same reasoning as
// generateUnknownCallerPhone above. "sim.example" is a reserved (RFC 2606)
// domain, so this address can never resolve to a real inbox.
export function generateUnknownCallerEmail(random: () => number = Math.random): string {
  const digits = Array.from({ length: 7 }, () => Math.floor(random() * 10)).join("");
  return `unknown-${digits}@sim.example`;
}

export function resolvePresetEmail(
  presetId: IdentityPresetId,
  random?: () => number,
): string {
  const preset = EMAIL_PRESETS.find((p) => p.id === presetId);
  return preset?.address ?? generateUnknownCallerEmail(random);
}
