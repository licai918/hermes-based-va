# S21 — Instrument the two proxy metric tiles

- **Milestone:** 0.0.4 — land all seven
- **Track:** T7 Metrics instrumentation
- **Size:** S
- **Depends on:** none (parallel-safe)
- **Delivers:** FR-30
- **Surface:** event emit sites + `datastore/handlers/metrics.py`; panel labels

## Goal

FR-30: `selfServiceUsage` (customer self-service query/delete events) and
`l6ConfirmedEntries` (L6 confirm events) become real counters emitted at
their sites; the `proxy:true` flags drop off the metrics API and panel.

## Approach

- Emit at the governed action sites (self-service tool path from 0.0.3 S21;
  L6 confirm path from 0.0.3 S24) — counter rows/events in the datastore,
  pooled-connection discipline respected (S29 note in `metrics.py:35`).
- Metrics handler aggregates the real events; BFF/panel drops the proxy
  labels.

## Acceptance — three-layer gate

- **① Technical:** emit-site tests (action → counter row); aggregation
  tests; no `proxy:true` left for these two tiles (grep-proof).
- **② E2E (browser):** perform a self-service query + an L6 confirm in the
  simulator/workbench; both tiles increment; screenshots.
- **③ Product (PAC):** feeds PAC-9.

## Out of scope

- Honored-rate — **S22**. New metrics beyond the two named.
