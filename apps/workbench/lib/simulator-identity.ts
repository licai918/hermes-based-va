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
// Extension points (comments only, no code yet):
// - S05 "link identity": a control that simulates the ingress event linking
//   the current simulated channel identity to a verified customer / another
//   channel identity. Slots in next to the preset picker in Simulator.tsx.
// - S18 channel switcher: presets are phone-shaped today; a channel switch
//   would need a parallel small preset table for email senders (see
//   `email_matches` in identity.py) rather than reusing this one directly.

export type IdentityPresetId = "verified" | "ambiguous" | "unknown";

export interface IdentityPreset {
  id: IdentityPresetId;
  label: string;
  /** Fixed phone for presets seeded in the mock identity driver; absent for "unknown", which generates fresh. */
  phone?: string;
}

export const IDENTITY_PRESETS: readonly IdentityPreset[] = [
  { id: "verified", label: "Verified customer (seeded)", phone: "+14165550101" },
  { id: "ambiguous", label: "Ambiguous match (seeded)", phone: "+14165550222" },
  { id: "unknown", label: "Unknown caller (fresh number)" },
];

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
