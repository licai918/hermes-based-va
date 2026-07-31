# S12 — Boundary tripwire tests: LAYER_OF_ACTION + composition + matrix rows

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T3 Boundary enforcement — **EARLY BIRD**
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-15, FR-16, FR-17
- **Surface:** tests + one declarative map (no behavior change)

## Goal

Tier-2 enforcement (C4): the documented boundaries become machine-checked. FR-15: a
`LAYER_OF_ACTION` map — every memory-writing catalog action declares exactly one layer;
completeness-tested so an undeclared new action fails CI. FR-16: injection-composition test —
≤1 fence per layer, no unfenced memory content (S06 later extends it with the precedence
assertion). FR-17: testable boundary-matrix rows become tests; doc-only rows explicitly
marked. US15.

## Approach

- `LAYER_OF_ACTION: dict[(tool, action) -> layer_table]` beside the catalog; test asserts
  every write action in the catalog appears exactly once (derive "write action" from the
  registry, not a hand list).
- Composition test drives `render_injection` with all layers populated and asserts fence
  uniqueness + no stray memory text.
- Matrix rows: L5-ingest-no-PII (S07-0.0.3 boundary report → asserted), L4 context-only
  (existing tripwires referenced), L6/L7 scan-on-write (referenced); unlockable rows listed in
  the test file docstring as doc-only — honesty over theater.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** all new tests green; a deliberately-undeclared dummy action makes the
  completeness test fail (proven then removed); full suites regress clean.
- **② E2E:** carve-out — test-only slice, ① only (named per NFR-1).
- **③ Product (PAC):** feeds PAC-9.

## Out of scope

- Write-time advisories — **S13**. Sweeps — **S20**. Any runtime behavior change.
