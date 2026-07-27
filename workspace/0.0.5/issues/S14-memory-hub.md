# S14 — Memory Hub: one page mirroring L1-L7 with live counts

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T4 Memory-ops UX
- **Size:** S
- **Depends on:** S01 (for the L7 row's counts)
- **Delivers:** FR-21
- **Surface:** new admin page + one aggregate read (reuses existing reads)

## Goal

FR-21 (grill-locked: sits ABOVE the consoles, deep links stay): one "Memory" hub page — one
row per layer L1-L7 with status + live counts (pending proposals, zero-hit entries, last
ingest, last sweep, found-rate) and a deep link into each existing console. The architecture
diagram AS the UI; a new admin's mental model in one screen. US9's hub half.

## Approach

- One admin BFF aggregate read composing EXISTING reads (agent-experience list counts, lexicon
  counts, corpus status, retention status, metrics) — no new per-layer queries beyond cheap
  counts; admin-gated; NOT LLM-callable if a new action is added.
- Page mirrors the memory-layers.md at-a-glance table (same row order/labels — the doc and the
  UI stay twins); each row deep-links to its console.
- Counts freshness: on-load fetch (the health-probe staleness-honesty pattern for anything
  cached).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest — the hub payload carries a row per layer with the named counts;
  admin-gated route; tsc clean.
- **② E2E (browser):** the hub renders all seven layers with live numbers; clicking a row
  lands on the right console; screenshot.
- **③ Product (PAC):** PAC-5's hub leg.

## Out of scope

- The unified inbox — **S15**. Nav restructuring beyond adding the hub entry.
