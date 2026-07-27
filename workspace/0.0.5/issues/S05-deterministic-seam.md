# S05 — Deterministic seam: per-handler param normalization + catalog verification

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T1 L7 Semantic Lexicon
- **Size:** M
- **Depends on:** S01, S03
- **Delivers:** FR-5
- **Surface:** shared helper called by product-read handlers (mock + real twins)

## Goal

FR-5 (grill-locked hook point): a shared PER-HANDLER helper — NOT dispatch middleware —
normalizes `search_products`/`get_product` params through confirmed aliases + enabled
normalizers before the query; parsed sizes are verified against the live catalog before the
agent asserts them. US2's hard half.

## Approach

- `normalize_product_query(params, domain_hints)` pure-ish helper: confirmed-alias exact map +
  enabled normalizers (S03), consulted from a process-level cache invalidated by S02's version
  bump (the S10-embedder singleton pattern).
- Explicit call sites: the two product-read actions in BOTH driver twins; enumerate at
  implementation and keep the list in the slice report.
- Catalog verification: a parsed size that matches no live product downgrades to the raw query
  + a clarify posture (never assert an unverified canonical).
- Fail-open: cache/DB trouble → raw params pass through unchanged (memory never stalls a
  reply, NFR-5).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit — all three 2055516 notations normalize to one canonical query; alias
  map applies; disabled normalizer = pass-through; cache honors version bump; failure
  pass-through proven. Live-PG + mock twin parity.
- **② E2E (browser):** simulator: the three notations each retrieve the same product;
  screenshots.
- **③ Product (PAC):** PAC-1's retrieval leg.

## Out of scope

- Prompt-side glossary — **S06**. New tool actions (none — helper only).
