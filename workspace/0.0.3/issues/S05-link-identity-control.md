# S05 — "Link identity" control (simulated verified ingress → Identity Graph link)

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T2 Conversation Simulator
- **Size:** S
- **Depends on:** S04
- **Delivers:** FR-13 (link-identity control)
- **Surface:** simulator page control; Identity Graph linking path (production semantics)

## Goal

FR-13 / audit finding 10: a simulator control that "simulate[s] the ingress
event that links the current simulated channel identity to a verified customer
(or to another channel identity), so the FR-19 cross-channel merge is
triggerable and observable from the simulator (PAC-4's E2E path)."

## Approach

- A control on the simulator page that issues the simulated link-ingress event
  through the production Identity Graph linking path — no direct DB writes.
- Covers both link shapes: channel identity → verified customer, and channel
  identity → channel identity.
- Before S19 lands, the link simply lands in the Identity Graph; the merge
  behavior it triggers is S19's scope.
- Governance posture (NFR-2 context): identities travel via the same ingress
  semantics as real linking — framework-derived binding, never tool/model params.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest: control → link event carrying the correct pair of
  identities. Integration (live Postgres): the Identity Graph reflects the link
  after the event.
- **② E2E (browser):** click "link identity" on a simulated conversation and
  observe the linked/verified status from the front end (simulator indicator,
  or the S20 audit view once it lands); screenshot.
- **③ Product (PAC):** feeds PAC-4 — the owner triggers the SMS→email
  continuity path with this control at S19/S33.

## Out of scope

- Merge policy, slot movement, merge audit — **S19**.
- Email ingress — **S17**.
