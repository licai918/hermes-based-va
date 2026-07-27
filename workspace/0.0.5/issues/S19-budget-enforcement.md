# S19 — Memory budget enforcement: deadlines + fail-open + thread-pool parallelization

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T5 Latency
- **Size:** S-M
- **Depends on:** S18 (evidence-gated)
- **Delivers:** FR-27
- **Surface:** pre-turn load sites in both turn paths

## Goal

FR-27 (C2, grill-locked mechanisms): every pre-turn memory read is deadline-bounded +
fail-open (the L5-deadline discipline generalized — memory may degrade a reply's context,
never stall it), and the independent pre-turn loads run in a `ThreadPoolExecutor` with
sequential fail-open fallback — applied ONLY where S18's histogram indicts. US14.

## Approach

- Per-layer read deadlines (cheap: L4/L6/L7 get short bounds; L5 already has 800ms) → on
  breach, skip that layer's injection for the turn + emit the skip (countable).
- Parallelization: pool over the independent loads (merge is a write — keep its ordering
  semantics; parallelize the reads it doesn't feed); ANY pool error degrades to today's
  sequential path.
- Ship dark if the SLO is already met: land the mechanisms flag-gated, enable on evidence —
  the slice is NOT license to optimize an un-indicted path (ponytail).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** a deliberately-slow fake store breaches the deadline → the turn completes
  without that layer + the skip is counted; pool-failure test degrades sequentially with
  identical results; existing turn suites byte-identical under the flag OFF; replay green.
- **② E2E (browser):** with an injected slow layer, the simulator still answers promptly and
  the panel shows the skip; screenshot.
- **③ Product (PAC):** PAC-6's enforcement leg.

## Out of scope

- Async rewrite of the turn runner (rejected). Cache redesigns beyond existing patterns.
