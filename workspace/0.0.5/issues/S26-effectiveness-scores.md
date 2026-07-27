# S26 — Per-entry effectiveness: score×ledger join + injection-stratified sampling

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop
- **Size:** M
- **Depends on:** S09 (ledger), S21 (legs)
- **Delivers:** FR-31
- **Surface:** join view/aggregate; S22-judge-job sampling change; retirement feed upgrade

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

## Out of scope

- Hit-ranked glossary selection flip (a follow-up toggle once scores stabilize — noted, not
  silently on). Loop metrics — **S28**.
