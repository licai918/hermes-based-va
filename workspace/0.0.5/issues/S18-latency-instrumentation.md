# S18 — Per-layer latency instrumentation + SLO tiles

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T5 Latency — **EARLY BIRD**
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-26
- **Surface:** duration emits at each memory-read site; metrics-panel tiles

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D5.1 — you need a migration; the Surface line saying otherwise is corrected to prefix
  0023.** `metric_event` is `(id, metric TEXT, flag BOOLEAN, created_at)` — there is **no
  numeric column**, so p50/p95 over it is arithmetically impossible. Encoding a duration into
  the metric *name*, or degrading it to a boolean "was slow", satisfies the letter of the
  Approach below and is a defect. Ship either a latency-sample table or a nullable numeric
  column on `metric_event`; pick one and document why.
- **D5.2 — the 150ms p95 SLO covers NON-L5 pre-turn reads only.** L5's own shipped budget is
  800ms (`knowledge/driver.py DEFAULT_DEADLINE_MS = 800.0`), so a total that includes L5 can
  never meet 150ms. FR-27 already scopes enforcement to non-L5 reads. Measure and tile L5 —
  against its own 800ms budget — but exclude it from the SLO total.
- **D5.3 — `merge` is a write, not a read.** Instrument it (it is on the pre-turn path and it
  matters) but give it its own tile outside the read-SLO total. S19 excludes it from
  parallelization for the same reason.

## Goal

FR-26 (C2, measure-first): per-layer read-duration emits (eval-neutral, fire-and-forget — the
S26-0.0.3 metric_event pattern) + p50/p95 tiles per layer on the metrics panel, with the
recorded SLO line: **≤150ms p95 total pre-turn reads** (owner decision ②). No optimization in
this slice — the histogram comes first. US13.

## Approach

- Wrap each pre-turn read site (L4 load, merge, L6 load, L7 load when S06 lands, L5 in-turn
  retrieval) with a duration emit — metric name per layer + a total; gated exactly like the
  existing emits (feature's own flag; eval/mock paths emit nothing).
- Aggregation: reuse metric_event + a p50/p95 view (or the honored-rate-aggregate job pattern
  if percentiles need a scheduled rollup — implementer's choice, documented).
- Panel: one tile per layer + the total-vs-SLO tile (breach renders visibly, honest-labeling
  house style).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit — emits fire on the datastore path with plausible durations and are
  absent on mock/eval paths (replay suite green); tile payload carries per-layer p50/p95 +
  SLO status; tsc clean.
- **② E2E (browser):** drive simulator traffic → tiles show live numbers vs the 150ms line;
  screenshot.
- **③ Product (PAC):** PAC-6.

## Out of scope

- ANY optimization (deadlines/parallelization) — **S19**, gated on this data.
