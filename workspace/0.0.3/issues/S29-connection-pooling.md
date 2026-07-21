# S29 — Pooling at all 4 sites (dispatch, gateway store, per-turn drivers, knowledge DB) under parallel sim load

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T8 Hygiene
- **Size:** M
- **Depends on:** none (verification uses the simulator; knowledge-DB site lands with S06/S09)
- **Delivers:** FR-31
- **Surface:** Postgres connection handling at the four sites named by FR-31

## Goal

FR-31: "pooled Postgres connections at **all four connection sites** (audit
finding 9): the dispatch servers, the gateway store, the **per-turn
`extra_drivers` memory-driver connections** (C4's original motivation — ~2–3
connections per turn), and the new **knowledge-DB driver**; behavior verified
under parallel simulator load."

## Approach

- Introduce pooling at each of the four sites, preserving the lazy-DSN seams
  (datastore pattern, `KNOWLEDGE_DATABASE_URL`).
- **RK-8:** pool introduction changes connection semantics under concurrency —
  the acceptance explicitly exercises parallel simulator load before sign-off
  (PAC-9); pool sizing knobs are implementer's choice.
- No behavior change intended at the seams — existing suites are the
  regression guard.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** integration (live Postgres): under a parallel-turn test the
  Postgres connection count stays bounded at each of the four sites; all
  existing datastore/driver suites stay green.
- **② E2E (browser):** run multiple simulated conversations in parallel from
  the simulator — all complete with replies, no connection-exhaustion errors;
  screenshot of the concurrent threads (connection evidence from logs/metrics
  alongside).
- **③ Product (PAC):** PAC-9's pooling leg — "pooling holds under parallel
  simulator load," owner-driven.

## Out of scope

- Retention sweep — **S28**; CI Postgres — **S30**.
- Any cloud/deployment change — **out (§9, ADR-0142 local-first)**.
