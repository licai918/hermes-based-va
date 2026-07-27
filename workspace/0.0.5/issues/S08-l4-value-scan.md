# S08 — L4 value injection scan (hard-reject)

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T2 Lifecycle core
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-10
- **Surface:** `_require_value` / upsert path (mock+PG); shared scanner

## Goal

FR-10 (closes verified gap 2; owner decision ④): L4 slot VALUES pass the shared injection/PII
scanner at write time — injection patterns **hard-reject** with a governed error; today
`_require_value` checks only type+length and the read-side fence is the sole mitigation. US6.
Exploration C5 §5.1/§5.5.

## Approach

- Extend the ONE shared scanner (S22-origin, already single-sourced mock↔PG) to the L4 upsert
  value (and evidence field) — same call in both twins (NFR-7).
- Hard-reject for instruction-injection patterns (`policy_blocked`-class governed error,
  nothing persists); keep the 200-char cap; scan rejections emit a pollution-metric event
  (consumed by S22).
- The customer-facing turn surfaces the existing governed-refusal posture (no raw error).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit (mock) + live-PG — "ignore previous instructions…" as a delivery note
  rejects with zero rows and one metric event; benign values persist unchanged; all existing
  memory suites green; tripwire green.
- **② E2E (browser):** simulator: the malicious note draws a normal reply and NO slot appears
  in the Memory Audit view; screenshot.
- **③ Product (PAC):** PAC-4's write-side leg.

## Out of scope

- Adversarial EVAL family — **S23**. Pollution-rate tile — **S22**.
