# S27 — Judge tuning: rubric + model option + labelled fixture set measuring judge precision/recall

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T7 Measurement
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-29
- **Surface:** judge rubric/prompt + model config; labelled fixture set + runner; admin eval report

## Goal

FR-29: "judge tuning: sharpened rubric/prompt, configurable stronger judge
model, and a small labelled fixture set measuring the judge's own
precision/recall (fixes the '2pm ETA vs after-2pm preference' conflation
class); judge remains advisory, never gating."

## Approach

- Sharpen the judge rubric/prompt; make the judge model configurable with a
  stronger-model option.
- Build a small labelled fixture set (including the ETA-vs-preference
  conflation class) and a repeatable runner reporting the judge's own
  precision/recall.
- The judge report surfaces on the admin eval/metrics entry alongside the S12
  recall report (FR-7's surfacing rule).
- **Advisory only — the judge never gates CI**; the deterministic replay gate
  remains the hard gate (NFR-6).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** the runner reports judge precision/recall on the labelled
  set as a repeatable command; the conflation-class fixtures are scored
  correctly by the tuned judge; eval replay unaffected.
- **② E2E (browser):** the judge report is visible on the admin eval/metrics
  entry (NFR-1: dev-harness outputs satisfy ② via the surfacing panel);
  screenshot.
- **③ Product (PAC):** PAC-8's judge leg — "the judge fixture report shows the
  judge's own accuracy on the labelled set."

## Out of scope

- Metrics aggregation + honored-rate sampling wiring — **S26**.
- Any judge-gated CI behavior — **explicitly excluded (advisory only)**.
