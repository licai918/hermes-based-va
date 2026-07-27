# S08 — Implicit draft outcome write path (`record_draft_outcome`)

- **Milestone:** 0.0.4 — quality-feedback (module)
- **Track:** T3 Internal draft feedback
- **Size:** S
- **Depends on:** S06 (owns the table and the shared gate)
- **Delivers:** FR-1, FR-4, FR-9 (write half), NFR-2
- **Surface:** mock + Postgres handlers for `record_draft_outcome`; no UI

## Goal

Persist the highest-signal, zero-effort measurement the system produces: whether
the rep sent the generated draft untouched, or edited it first — and by how much.

A draft sent unchanged is a good draft. That judgment costs the rep nothing, so
it will exist for far more drafts than explicit ratings will.

## Approach

- Handler for `record_draft_outcome` writing into the `draft_feedback` table from
  S06, with outcome `sent_as_is` or `sent_edited` and, when edited, a normalized
  edit-distance ratio.
- Reuses S06's fail-closed actor resolver and the same case-ownership gate — an
  outcome is a governed write like any other.
- Validates outcome in enum; requires the correlation id and the generated-draft
  snapshot; requires the ratio when and only when the outcome is `sent_edited`.
- Rows written here and by S07 share the correlation id, so one draft's implicit
  and explicit signals join.

## Acceptance — three-layer gate

- **① Technical:** live-Postgres — an `sent_as_is` row and a `sent_edited` row
  with a plausible ratio, both SELECTed back; a rating (S07) and an outcome for
  the same draft share one correlation id and are two distinct rows. No-actor and
  unclaimed-case dispatches → `policy_blocked` with zero rows. Ratio required on
  `sent_edited`, rejected on `sent_as_is`.
- **② E2E (browser):** carve-out — the UI wiring is **S09**.
- **③ Product (PAC):** feeds PAC-4.

## Out of scope

- Deciding as-is vs edited, computing the distance, and the fire-and-forget call
  — all client-side, in **S09**. This slice only accepts and persists the verdict
  it is handed.
