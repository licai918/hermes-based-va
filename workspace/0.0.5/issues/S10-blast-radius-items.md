# S10 — Blast-radius repair: affected-cases query + inbox review items

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T2 Lifecycle core
- **Size:** S-M
- **Depends on:** S09, S15
- **Delivers:** FR-12
- **Surface:** ledger query (admin read); inbox item kind

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D4** — S09's `entry_ref` is a stable NATURAL key, not a row id: `binding_key + slot_name`
  for L4, the entry id for L6/L7. The cross-channel merge path DELETEs and re-INSERTs L4 rows
  with new ids, so your affected-cases join must key on `entry_ref` as defined, never on an L4
  row id — joining on a row id silently drops or misattributes cases after any merge.
- **D17** — you are the LAST slice in the serialized catalog-touching order (S01 → S02 → S15 →
  S11 → S10). Confirm the nine-file catalog sync set (tool_catalog.py, plugin.yaml, schemas.py,
  profiles.py, plugin/__init__.py, mock/__init__.py, handlers/__init__.py, tools.ts, drift
  tests) is clear of in-flight work from the earlier slices before you touch it, and re-list it
  in your report as the earlier slices did.
- **Never group blast radius by `case_or_binding_ref` alone.** S09's merge now re-points
  `entry_ref` when a provisional binding is verified, so pre- and post-verification rows agree on
  the entry — but `case_or_binding_ref` is deliberately **not** re-pointed, because that turn
  genuinely did happen under the provisional binding and rewriting it would falsify history.
  Group by `entry_ref`; if you also need the case, treat provisional and verified refs for the
  same customer as one, or a single customer reads as two and the "N open cases touched" count
  is wrong in the direction that matters.
- **Dedupe by case on the copilot path.** A draft turn has no durable identity, so its `turn_ref`
  is a synthetic id that never repeats; the composite primary key therefore cannot dedupe it, and
  a re-drafted case accumulates duplicate per-entry rows.

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
