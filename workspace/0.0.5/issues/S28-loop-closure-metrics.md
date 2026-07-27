# S28 — Loop-closure metrics: conversion, post-fix re-fail, honored trends

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop
- **Size:** S
- **Depends on:** S25, S26
- **Delivers:** FR-34 (loop half)
- **Surface:** metrics panel tiles (SQL over existing rows)

## Goal

FR-34b (C6 §6.5 — proving the loop closes): **feedback→proposal conversion rate**, **post-fix
re-fail rate** (the same tag recurring on the same subject AFTER a confirmed fix — the single
most honest "did the loop work" number), and **per-entry honored trend after a replacement**.
The loop becomes measurable end to end: score → aggregate → propose → confirm → inject → next
scores move. US19.

## Approach

- All three are SQL joins over rows earlier slices write (feedback tables × aggregator
  proposals × decisions × ledger/judge aggregates) — zero new emit seams.
- Post-fix re-fail: window + subject-matching rule documented as named constants (knob panel).
- Tiles join the S22 panel section; PROXY/advisory labeling where a number is trend-thin early
  (no silent zeros).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** seeded fixtures — a confirmed fix followed by a recurrence counts as ONE
  re-fail; a fix with no recurrence counts clean; conversion math correct; vitest + live-PG;
  tsc clean.
- **② E2E (browser):** the loop tiles render after driving the seeded S25→S15-accept path;
  screenshot.
- **③ Product (PAC):** PAC-7's closing half.

## Out of scope

- New signals or actuators — this slice only measures the loop the others built.
