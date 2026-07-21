# S25 — Confirmed-entry injection (copilot; external read-only behind own flag) + eval pinning; L6 ADR

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T6 Agent-experience L6
- **Size:** M
- **Depends on:** S24
- **Delivers:** FR-25, FR-26, FR-27, NFR-5, NFR-6, NFR-8 (L6 ADR)
- **Surface:** copilot draft turn + external turn injection; eval path pinning; ADR docs

## Goal

FR-25: injection of **confirmed** entries only — copilot draft turn first
(build order); "the **external turn also reads confirmed entries** — per the
grilled decision's exact wording ('外部 agent 只读已确认条目': read-only over
confirmed learnings, never proposing) — **behind its own flag** so it can be
disabled independently" (audit finding 5). FR-26: eval determinism — L6
injection pinned/disabled on the eval path. FR-27: validated with simulator
traffic. Ships the **L6 ADR**.

## Approach

- Copilot draft turn injects confirmed entries (US19); `proposed` and
  `rejected` entries are never injected anywhere.
- **External turn: read-only over confirmed entries, never proposing (§9),
  behind its own independent flag** — disable-able without touching the
  copilot path.
- Turn resilience (NFR-5): injection degrades to skip on any failure — the
  turn never fails on L6.
- **Eval pin (NFR-6):** L6 injection pinned/disabled on the eval path; the
  deterministic replay gate (ADR-0119) stays the CI hard gate and stays green
  (US29).
- **L6 ADR (NFR-8):** records the one-store decision (FR-23), the
  operational-only rule, the external read-only interpretation, and the
  deferred post-launch real-traffic calibration (FR-27).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit: only `confirmed` entries injected; external flag off
  → no external read; injection failure → skip, turn completes; eval replay
  green with the pin asserted in the eval config. L6 ADR present in the build.
- **② E2E (browser):** confirm an entry via S24 → a later copilot draft turn
  visibly applies it; a rejected entry is never applied; toggle the external
  flag and show the external turn with/without the read; screenshots.
- **③ Product (PAC):** PAC-7 full — "confirmed → visibly applied in a later
  draft turn; rejected → never applied."

## Out of scope

- Review queue — **S24**; proposal generation — **S23**.
- L6 real-traffic calibration — **post-launch (§9, recorded in the ADR)**.
