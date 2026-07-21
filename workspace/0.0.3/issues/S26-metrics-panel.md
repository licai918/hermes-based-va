# S26 — Aggregate metrics + admin panel (honored rate, proposal accept rate, knowledge found rate)

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T7 Measurement
- **Size:** M
- **Depends on:** S10, S15, S21, S25 (their counters must exist)
- **Delivers:** FR-28
- **Surface:** metrics aggregation over existing observability + new counters; admin metrics entry

## Goal

FR-28: "aggregate metrics + admin panel: memory injection rate,
slots-populated distribution, **honored rate** (advisory, judge-sampled — the
C7 core question 'does the agent act on it'; audit finding 6), merge count,
correction count, proposal accept/dismiss rate, knowledge `found` rate,
self-service usage — computed from existing observability + new counters,
rendered on an admin metrics entry."

## Approach

- Aggregation over existing observability plus the counters landed by the
  upstream slices (S10 knowledge found, S15 accept/dismiss, S21 self-service,
  S25 L6 injection); this slice computes and renders — it does not re-implement
  the producers.
- **Honored rate is judge-sampled and advisory — never gating.**
- Admin metrics entry per ADR-0093; whether it shares the S12 eval surface or
  sits beside it is implementer's choice.
- Which business-outcome metric matters most (CSAT / handle time /
  repeat-contact) stays an **owner question** during the iteration; the panel
  ships with the mechanical metrics regardless.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit: metric computations correct on fixture data
  (rates/counts/distribution); vitest BFF: panel route payload carries every
  FR-28 metric.
- **② E2E (browser):** generate simulator activity, open the metrics panel —
  the counters visibly reflect it (knowledge found rate, proposal accept rate,
  honored rate present); screenshot.
- **③ Product (PAC):** PAC-8 — "the metrics panel reflects simulator activity"
  (the judge-accuracy half is S27).

## Out of scope

- Judge rubric/fixtures — **S27**.
- The counter-producing features themselves — **S10/S15/S21/S25**.
