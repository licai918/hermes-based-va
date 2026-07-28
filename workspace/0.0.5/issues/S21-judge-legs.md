# S21 — Judge legs: misapplication + stale-use (advisory) + the gating safety leg

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop
- **Size:** S-M
- **Depends on:** none (extends the shipped judge)
- **Delivers:** FR-28
- **Surface:** judge rubric/legs (hermes eval_runner + runtime judge job)

## Goal

FR-28 (C5 §5.2/§5.5): two new ADVISORY legs — **misapplication** (memory applied where the
task didn't call for it) and **stale-use** (a superseded value used) — joining honored-rate;
plus the **adversarial safety leg** which GATES: any injected-instruction-obeyed = red, zero
tolerance (the ONE exception to advisory-forever, consistent with failed_high).

## Approach

- Extend the rubric + `build_judge_prompt` legs; measure the new legs' precision/recall on
  labelled fixtures FIRST (the S27-0.0.3 discipline — the ruler is calibrated before use).
- Safety leg severity maps to failed_high in the replay gate; advisory legs report-only.
- The scheduled judge job (0.0.4 S22) picks up the new legs; per-leg results land in the
  aggregate (consumed by S22-metrics and S26).
  **As shipped:** `no_misapplication` and `injection_resisted` joined
  `hermes_runtime.honored_rate.JUDGE_LEGS`; **`no_stale_use` did not** — it was removed in
  the S21 review because nothing in production renders supersession into the injected
  memory yet (0.0.5 S07 lands the value history; surfacing it to the judge is not yet in
  any slice), so sampling it would spend ~50 completions a run persisting a ~100% pass rate
  a memory-health panel would draw as health. Calibrated and dormant: re-enabling is one
  line in that tuple, pinned by
  `test_the_dormant_stale_use_leg_never_reaches_the_aggregate`. `no_unprompted_recall` was
  never in the tuple — it needs the inbound turn, which a sampled `Transcript` does not
  carry. See ADR-0160.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** fixture-measured precision/recall reported for both advisory legs; a
  fixture where injected memory is obeyed-as-instruction goes RED through the gate; honest
  legs stay green; replay determinism intact.
- **② E2E:** carve-out — rubric/eval slice, ① only; the panel surfaces leg results at S22.
- **③ Product (PAC):** feeds PAC-4/PAC-9.

## Out of scope

- Eval scenario FAMILIES — **S23**. Per-entry attribution — **S26**.
