# S20 — Graduation sweep + zero-hit retirement feed

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T3 Boundary enforcement
- **Size:** M
- **Depends on:** S01, S15
- **Delivers:** FR-19, FR-20
- **Surface:** scheduled job (S04-0.0.4 worker pattern); inbox item kinds

## Goal

Tier-4 enforcement (C4, grill-locked: SCHEDULED, not event-driven). FR-19: a sweep flags
confirmed L6 notes that are structurable (the S13 heuristic re-applied to CONFIRMED rows) as
"graduate to L7?" inbox items. FR-20: zero-hit entries (L7 hit_count / L6 usage over a
window) surface as retirement candidates — the free-text catch-all drains routinely into the
structured layer, dead vocabulary retires instead of accumulating. US16/US17.

## Approach

- One scheduled job, watermarked, propose-only (NFR-3): emits graduation + retirement inbox
  items with the entry + evidence; deciding them uses S15's existing actions (graduation
  Accept ≈ Re-classify L6→L7; retirement Accept = the existing retire).
- Window + thresholds are named constants (calibratable); zero-hit merges into S26's
  entry-health score once that lands (this slice ships the usage-only version, honestly
  labeled).
- Sweep visibility: last-run + counts on the retention/hub surfaces (S28-0.0.3 pattern).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** live-PG — a seeded structurable confirmed L6 note yields ONE graduation
  item (idempotent across runs); a zero-hit L7 entry past the window yields a retirement item;
  in-window/active entries yield nothing; job failure leaves queues clean.
- **② E2E (browser):** run the sweep → both item kinds appear in the inbox; accept a
  graduation → the L7 entry exists and the L6 note is re-filed; screenshots.
- **③ Product (PAC):** feeds PAC-5/PAC-9.

## Out of scope

- Effectiveness-scored retirement — **S26** upgrades the feed. Auto-graduation (forbidden).
