# S19 — Cross-channel provisional merge: policy + implementation + merge audit; merge ADR

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T4 Email + merge
- **Size:** M
- **Depends on:** S17, S05
- **Delivers:** FR-19, NFR-2, NFR-8 (merge ADR)
- **Surface:** identity-link event handling; provisional-slot merge path; merge audit

## Goal

FR-19: "when the Identity Graph links a channel identity to a verified customer
(or two channel identities to each other), provisional slots merge per a
defined precedence (never overwriting verified slots — ADR-0112 invariant);
merge audited; policy recorded as an ADR. The SMS→email continuity path is
demonstrable in the simulator." The **merge-policy ADR** ships with the build.

## Approach

- Merge triggered off the Identity Graph link event — the same event S05's
  simulator control emits, so the path is triggerable and observable end-to-end.
- Precedence policy defined and recorded in the **merge ADR** (NFR-8);
  verified slots are never overwritten (ADR-0112 invariant); merged writes
  carry the existing `merged_provisional` semantics through the framework-
  derived source path.
- Every merge writes an audit record, visible in the S20 view's write history.
- **ADR-0148 invariants must not break (NFR-2):** `source` /
  `actor_account_id` framework-derived, never model-supplied; context-only
  binding; unresolvable identity fails closed (`policy_blocked`); the removal
  tripwire stays green.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit: precedence cases — provisional → empty target slot
  merges; provisional vs verified → verified wins; channel↔channel link path.
  Datastore integration (live Postgres): link event → slots merged + merge
  audit row read back; removal tripwire green. Merge ADR present.
- **② E2E (browser):** in the simulator: state a provisional preference over
  SMS, click "link identity" (S05), open an email conversation (S18) → the
  preference is honored; screenshot of the email thread honoring it.
- **③ Product (PAC):** PAC-4 — the owner runs the full SMS→email continuity
  path, per the merge policy.

## Out of scope

- The link-identity simulator control — **S05**.
- Rendering merge history in the audit view — **S20**.
