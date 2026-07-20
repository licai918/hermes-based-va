# S23 — Learning loop: post-copilot-turn review pass (fork pattern), operational-only proposals

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T6 Agent-experience L6
- **Size:** M
- **Depends on:** S22
- **Delivers:** FR-22, NFR-3
- **Surface:** post-copilot-turn review pass (ported Hermes review-fork pattern) writing to the S22 store

## Goal

FR-22: "after a copilot turn, a bounded review pass (Hermes review-fork
pattern, ported — not Hermes's own store) may emit **operational-learning
proposals** (procedures, conventions, tool quirks — explicitly NOT customer
facts/PII; the review prompt forbids person-specific data)."

## Approach

- Port the review-fork pattern; the pass runs after a copilot turn and writes
  proposals into the S22 store via the governed tool, as `proposed`.
- **Operational-only rule (NFR-3 / RK-5): no customer facts or PII in
  proposals — the review prompt explicitly forbids person-specific data.** The
  S22 injection scan is the second line of defense; the human confirm gate
  (S24) is the third.
- Copilot turns only — the external turn never proposes (§9).
- Bounded: a single review pass per copilot turn; frequency/cost knobs are
  implementer's choice.
- Validation source is simulator traffic (FR-27); real-traffic calibration is
  deferred post-launch and recorded in the L6 ADR (S25).
- Turn resilience: a review-pass failure never fails the copilot turn.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit: the pass emits well-formed operational proposals into
  the store as `proposed`; a fixture turn full of customer facts yields no
  person-specific proposal (prompt rule + scan); a review-pass error leaves the
  copilot turn unaffected.
- **② E2E (browser):** run a simulated copilot session (simulator customer
  side + workbench rep side) → a learning proposal appears in the admin L6
  list; screenshot.
- **③ Product (PAC):** PAC-7's first leg — "a simulated copilot session yields
  a learning proposal" (full PAC after S24/S25).

## Out of scope

- Store, scan, governed tool — **S22**.
- Confirm gate UI — **S24**; injection of confirmed entries — **S25**.
