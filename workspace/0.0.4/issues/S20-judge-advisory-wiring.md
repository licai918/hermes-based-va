# S20 — Judge advisory wiring (every PR, real model) + live-eval ADR

- **Milestone:** 0.0.4 — land all seven
- **Track:** T6 Eval completion
- **Size:** M
- **Depends on:** S18
- **Delivers:** FR-28, FR-29, NFR-7
- **Surface:** CI workflow + judge runner wiring + ADR; no product code

## Goal

FR-28 (grilled decisions 13–14): every PR runs the live-model harness +
tuned judge (S27 baseline) over the scenario set and attaches an **advisory
report** — visible, never blocking. The scripted replay gate stays the only
required eval check (NFR-7).

## Approach

- CI job (non-required): S18 harness in `live` mode + `JudgeClient` with the
  S27-tuned rubric/model; report rendered as a CI artifact + PR comment
  (verdicts, misses, honored/no-unprompted-recall legs).
- No retry theater: advisory jobs report what happened; flakes are data,
  not failures to suppress (FR-29 records this stance).
- **Live-eval ADR**: harness architecture, advisory-forever stance (gate
  promotion = future ADR with measured judge precision), every-PR real-model
  cadence + cost note.

## Acceptance — three-layer gate

- **① Technical:** a PR shows the advisory job attaching a complete report
  while remaining non-required; required wall unchanged (NFR-7 proof).
- **② E2E (browser):** the PR page: required checks green + advisory report
  comment; screenshot.
- **③ Product (PAC):** PAC-8 — owner reads one report end-to-end.

## Out of scope

- Judge as a gate (PRD §6). Judge rubric changes (S27 baseline is input).
