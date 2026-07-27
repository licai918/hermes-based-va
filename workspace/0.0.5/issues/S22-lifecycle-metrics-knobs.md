# S22 — Lifecycle metrics + per-customer memory-health strip + knob panel

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop
- **Size:** M
- **Depends on:** S07, S08, S11 (their signals); S21 (leg results)
- **Delivers:** FR-34 (lifecycle half)
- **Surface:** metrics panel extensions; Memory Audit strip; knob panel (+control-loop ADR section)

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D14 (owner-flagged, default taken)** — the Goal's "audited config change path" is dropped.
  A panel that just renders env-var names is not an audited change path, so the knob panel ships
  honestly labelled READ-ONLY this iteration, and 0.0.5 records that NFR-3's knob clause is
  satisfied by deploy-time config only (knob changes are git-auditable because they are
  code/config commits), with no in-app enforcement. The owner may instead fund a real governed
  config action + audit row + config table as a follow-up; until then, do not build a fake
  toggle to satisfy the letter of the Goal.
- **D16** — the panel renders the named module constants earlier slices already introduced
  (S06's glossary-N, S20's zero-hit/prune windows, S25's N=3/M=3) by importing them, not by
  re-typing their current values. If an earlier slice shipped a bare literal instead of a
  constant, that is a defect in that slice, not something to work around here with a hardcoded
  display value.

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
