# S26 — Per-entry effectiveness: score×ledger join + injection-stratified sampling

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop
- **Size:** M
- **Depends on:** S09 (ledger), S21 (legs)
- **Delivers:** FR-31
- **Surface:** join view/aggregate; S22-judge-job sampling change; retirement feed upgrade

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D1** — the effectiveness rollup migration is allocated prefix **0028**. Re-verify by
  listing the migrations directory before writing yours.
- **D6** — `hit_count` going into the entry-health formula is the MATERIALIZED column S05's
  scheduled rollup maintains (migration 0026) — read it, don't recompute it from raw hit events
  or re-derive it from the ledger yourself. Ledger-derived honored/misapplied/stale rates come
  from the join you build here; hits come from the already-materialized column.
- **You own the judge-sample join, and a stale note is waiting for you.**
  `honored_rate.sample_transcripts` carries a `ponytail:` comment that still describes the
  injection ledger as missing — S09 shipped it (`injection_ledger`, migrations 0030/0031) and
  deliberately left the rewiring to you, since stratifying the judge sample by ledger presence is
  this slice's FR-31 work. Update that note as part of your diff; a comment asking for a table
  that now exists sends the next reader looking for work already done.
- **Per-entry effectiveness is EXTERNAL-PATH ONLY, and must say so where it renders.** The
  copilot path's `turn_ref` is a synthetic id with no durable identity, so its rows cannot be
  attributed per turn. A health score presented without that scope reads as "this entry's
  effectiveness everywhere", which it is not.

## Goal

FR-31 (C6 §§6.1/6.6 — the join that makes scoring the memory system's sensory organ): judge
verdicts × the injection ledger = **per-entry** honored / misapplied / stale rates; combined
with hit_count into ONE **entry-health score** driving the retirement queue (upgrading S20's
usage-only feed). Plus the **injection-stratified sampling** change: the scheduled judge job
prefers turns the ledger says carried injections — judge budget concentrates where memory
actually appeared. US17.

## Approach

- The join is SQL over existing rows (ledger + judge aggregates) — a view or scheduled rollup
  (the honored-rate-aggregate pattern); no new emit seams.
- Entry-health = documented formula over (hits, honored, misapplied, stale) with named weights
  (knob panel); retirement items (S20) now carry the score + its components.
- Sampling change in the S22-0.0.4 job: stratify by ledger presence; keep a floor of
  non-injection turns so the no-unprompted-recall leg still gets samples (honesty: don't blind
  the other eye).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** live-PG — seeded ledger rows + seeded verdicts produce correct per-entry
  rates and a deterministic health score; the stratified sampler picks injection turns
  preferentially with the documented floor; retirement feed shows scores.
- **② E2E (browser):** an entry's health score + components render on its console/queue row;
  screenshot.
- **③ Product (PAC):** feeds PAC-7/PAC-9.

- **Hit-ranked glossary selection toggle (gap-audit fix — FR-6's upgrade clause, previously
  orphaned, now IN scope here):** ship the selection strategy as a knob (newest-20 default →
  hit/health-ranked), flipped when scores stabilize; the flip is an audited admin/config
  action, both strategies tested.

## Acceptance addition

- **①:** the ranked strategy selects by entry-health deterministically on seeded scores; the
  default remains newest-20 until flipped; flip is audited.

## Out of scope

- Loop metrics — **S28**.
