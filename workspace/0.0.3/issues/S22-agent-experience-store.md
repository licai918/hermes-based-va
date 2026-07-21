# S22 — `agent_experience` store (status + `kind` note|procedure) + governed tool + injection scan

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T6 Agent-experience L6
- **Size:** M
- **Depends on:** none
- **Delivers:** FR-23, NFR-3
- **Surface:** business datastore (new governed table); governed write tool; minimal admin L6 list

## Goal

FR-23: "governed storage: an `agent_experience` store in the business datastore
with `status` (`proposed` / `confirmed` / `rejected`), `source`, proposer
context, decider + timestamp; injection-scanned on write (S09 discipline)."
Per audit finding 4, v1 is **one store with a `kind` field (`note` |
`procedure`)** — not Hermes's separate notes/skills stores.

## Approach

- New governed table in the business datastore — NOT Hermes's
  `MEMORY.md`/state.db (§7 seam 6: we port the *loop*, not the *store*;
  ADR-0140 boundary intact; Hermes built-in memory stays off).
- Columns per FR-23: `status`, `kind` (note|procedure), `source`, proposer
  context, decider + timestamp.
- Governed write tool creating `proposed` entries; **injection scan on write**
  (the 0.0.2 S09 hardening discipline is the floor — RK-5).
- Operational-only content (NFR-3) is the store's contract; the prompt-side
  enforcement lands with S23's review pass.
- The one-store decision + its revisit condition (procedures outgrowing flat
  entries) are recorded in the L6 ADR at S25.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit: governed tool writes `proposed` entries with kind +
  proposer context; injection scan rejects seeded adversarial content.
  Datastore integration (live Postgres): schema + status/decider/timestamp
  lifecycle fields persisted and read back.
- **② E2E (browser):** a seeded proposed entry is visible on a minimal admin
  L6 list entry (created here; S24 extends it into the review queue);
  screenshot.
- **③ Product (PAC):** feeds PAC-7 at S24/S25/S33.

## Out of scope

- The review-pass loop that generates proposals — **S23**.
- Confirm-gate queue UI — **S24**; injection of confirmed entries — **S25**.
