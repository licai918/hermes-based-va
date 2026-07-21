# S21 — Verified-only self-service: safe summary + governed clear + unverified deflection

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T5 Transparency & control
- **Size:** M
- **Depends on:** none
- **Delivers:** FR-21, NFR-2
- **Surface:** external turn governed tools (summary read, clear); no new write paths

## Goal

FR-21: "customer self-service, **verified customers only**: 'what do you
remember about me' → customer-safe summary (slot values, no internal metadata);
'forget me' → governed clear + audit; unverified callers receive a safe
deflection. Both flows via governed tools on the external turn — no new write
paths." (US11–13.)

## Approach

- Governed read tool returning a customer-safe summary: slot values only — no
  `source`, no `actor_account_id`, no internal metadata.
- Governed clear tool: audited deletion through the existing governed paths.
- Verification gate: unverified callers get a polite deflection and no data —
  memory cannot be probed by whoever holds a phone number (US13).
- Per the T5 deletion-honoring disposition (audit finding 2): FR-20 + FR-21
  **are** the v1 deletion mechanism; no org-wide erasure workflow exists to
  wire into (SMS opt-out is consent state, not erasure); re-opens when one
  exists (§9).
- **ADR-0148 invariants must not break (NFR-2):** context-only binding;
  unresolvable identity fails closed (`policy_blocked`); source/actor stay
  framework-derived; the removal tripwire stays green.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** driver-seam units (hermes/tests): verified → summary with
  slot values and no internal metadata; unverified → deflection, no data
  returned; clear → governed, audited deletion; unresolvable identity →
  `policy_blocked`. Datastore integration (live Postgres): cleared slots gone,
  audit row present; tripwire green.
- **② E2E (browser):** simulator: verified preset asks "what do you remember
  about me" → safe summary; "forget me" → honored (verify emptiness in the S20
  view); unknown-caller preset → deflection; screenshots.
- **③ Product (PAC):** PAC-6 — owner runs both the verified and unverified
  flows.

## Out of scope

- Supervisor-side clear + audit view — **S20**.
- Customer-facing web portal for memory — **out (§9; SMS self-service only)**.
