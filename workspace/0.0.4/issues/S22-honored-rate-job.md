# S22 — Honored-rate from a scheduled judge job

- **Milestone:** 0.0.4 — land all seven
- **Track:** T7 Metrics instrumentation
- **Size:** M
- **Depends on:** S04 (background worker), S20 (judge wiring)
- **Delivers:** FR-31
- **Surface:** typed queue job + metrics handler; panel label

## Goal

FR-31: honored-rate stops being a "non-live placeholder": a scheduled
`honored_rate` job (background worker) runs the tuned judge over recent
transcripts and persists the aggregate the metrics handler serves.

## Approach

- Typed job on the T2 queue: sample recent `message_turn` transcripts with
  memory injections, run the judge's honored leg, persist the aggregate
  (rate + sample size + window + run timestamp).
- Metrics handler reads the latest aggregate; panel shows value + "as of"
  provenance; placeholder label drops.
- Cost bounded: sampling cap per run recorded in the job config (log what
  was sampled vs skipped — no silent truncation).

## Acceptance — three-layer gate

- **① Technical:** job tests with scripted judge verdicts; aggregate
  persistence + read; retry/dead-letter inherited.
- **② E2E (browser):** trigger the job; panel shows a real rate with
  timestamp; screenshot.
- **③ Product (PAC):** PAC-9 honored-rate leg.

## Out of scope

- Judge rubric changes. Per-customer honored views.
