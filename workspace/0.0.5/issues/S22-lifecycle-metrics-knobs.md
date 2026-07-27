# S22 — Lifecycle metrics + per-customer memory-health strip + knob panel

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop
- **Size:** M
- **Depends on:** S07, S08, S11 (their signals); S21 (leg results)
- **Delivers:** FR-34 (lifecycle half)
- **Surface:** metrics panel extensions; Memory Audit strip; knob panel (+control-loop ADR section)

## Goal

FR-34a (C5 §5.8 + C6 §6.6): the lifecycle metric set on the panel — conflict rate (S07's
differing-value overwrites + queue conflict annotations), pollution rate (S08 scan rejections
+ poisoned-retirements), deletion success (S11), privacy-deflection proxy (owner ⑤ — honestly
labeled) — plus the **per-customer memory-health strip** on the Memory Audit console (slots
age, correction count, last-injection recency, clear history) and the **knob panel** (glossary
N, bounds, windows: read-only values + audited config change path — knobs move only by admin
action, NFR-3).

## Approach

- All counts are SQL over rows earlier slices already write — no new emit seams beyond what
  exists; PROXY/advisory labels per the no-silent-zero house style.
- Health strip composes existing per-binding reads (S20-0.0.3 + S07) — no new tables.
- Knob panel lists the named constants + their env/config override path; changes audited via
  the config mechanism (document; no in-UI mutation this iteration if config is file-based —
  honesty over a fake toggle).
- Record the Memory-Control-Loop decisions in the lifecycle/control-loop ADR (or extend the
  L7 ADR — implementer names it; NFR-8: same PR as this slice).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** metric computations correct on seeded fixtures; panel payload carries every
  FR-34a metric with labels; strip renders per-customer; vitest + tsc clean; live-PG
  aggregation.
- **② E2E (browser):** panel + strip + knob panel render live values; screenshots.
- **③ Product (PAC):** feeds PAC-3/PAC-4/PAC-9.

## Out of scope

- Loop-closure metrics (conversion/re-fail/trends) — **S28**. Effectiveness scores — **S26**.
