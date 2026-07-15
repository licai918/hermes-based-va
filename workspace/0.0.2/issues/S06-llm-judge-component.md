# S06 — LLM-judge component (advisory, injection-hardened, fixture-tested)

- **Milestone:** 0.0.2 — memory governance
- **Size:** M
- **Depends on:** none
- **Delivers:** FR-3/FR-6 infra, R5, RK-3
- **Surface:** eval-unit / judge component

## Goal

A reusable LLM-judge that inspects a reply for the honored / no-unprompted-recall
semantic legs — **advisory only** (never a CI gate), injection-hardened, on a
cheap model.

## Problem

The eval's semantic legs have no real inspector. FR-6/R5 need one that reads the
reply, and it must not become a flaky gate or an injection vector (RK-3). New
component — nothing like it exists today.

## Files (likely)

- new judge module under `hermes/eval_runner/` (component + prompt).
- fixture transcripts + a judge unit test.

## Approach

Per PRD §9 (semantic legs = LLM-judge, advisory, injection-hardened, cheap model),
NFR-3, RK-3:

- Cheap model (haiku). The judged reply **and** any injected untrusted memory are
  **fenced data, not instructions** (injection-hardening).
- **Advisory:** the judge never gates CI — its signal is recorded only. The
  `no-inferred` leg stays **mechanical** (not the judge).
- Unit-test at the **fixture-transcript** level (§6.3, highest seam that still
  exercises it): honored-yes, honored-no (ignored/re-asked), and an
  injection-attempt fixture that must **not** flip the verdict.

## Acceptance

- Unit **R5** (§6.3 FR-3 judge seam): a fixture where the preference is
  ignored/re-asked **fails** the honored judge (the freebie is gone); a genuinely
  honored fixture passes.
- Injection fixture: a fenced reply/memory carrying "ignore instructions…" does
  not flip the verdict.
- The judge is asserted **non-gating** (advisory) — NFR-3.

## Out of scope

- Wiring the judge into `turn_result`/`assertions` + the scenarios — **S08**.
- The mechanical no-inferred assertion — **S07**.
