# S10 — Blast-radius repair: affected-cases query + inbox review items

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T2 Lifecycle core
- **Size:** S-M
- **Depends on:** S09, S15
- **Delivers:** FR-12
- **Surface:** ledger query (admin read); inbox item kind

## Goal

FR-12: when an entry is corrected/retired/cleared, the ledger answers "which turns did it
touch" — open cases touched surface as inbox review items ("N open cases touched by retired
entry X — review?"); closed cases are sampled by business judgment, never auto-reopened. US8.
Exploration C5 §5.7.

## Approach

- Admin-only read (`_AGENT_EXCLUDED_ACTIONS`, the get_memory_audit precedent — **with the
  house `registered_names()` exclusion regression test**, gap-audit fix): affected turns/
  cases for an entry_ref since a timestamp, joined to case status.
- Hook: the retire/clear/edit decide paths (S02, L6 decisions, L4 clears) enqueue ONE
  **`review_item` row (kind=blast_radius, the S15 store)** carrying the affected-open-cases
  list as evidence — propose-only, human works it in the S15 inbox (NFR-3).
- No auto-action on any case; the item's actuators are acknowledge/dismiss + deep links.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** live-PG — seed injections across 3 cases (2 open, 1 closed) → retire the
  entry → item lists exactly the 2 open cases; acknowledge/dismiss audited; no case mutated.
- **② E2E (browser):** retire a seeded entry → the review item appears in the inbox with case
  links; screenshot.
- **③ Product (PAC):** PAC-3's blast-radius leg.

## Out of scope

- Case reopening/outreach automation (business judgment, out). Effectiveness scores — **S26**.
