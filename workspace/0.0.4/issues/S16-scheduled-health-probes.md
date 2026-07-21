# S16 — Scheduled integration health probes

- **Milestone:** 0.0.4 — land all seven
- **Track:** T5 Integrations ops surface
- **Size:** S
- **Depends on:** S04 (background worker), S15 (page to surface results)
- **Delivers:** FR-24
- **Surface:** typed queue job + probe records + page badge

## Goal

FR-24: a scheduled `integration_probe` job (background worker) runs a cheap
read per integration; failure surfaces as a page badge + structured log
alert — closing ADR-0136's "lazy discovery only" gap.

## Approach

- Typed job on the T2 queue, scheduled (same mechanism as the retention
  sweep's trigger); one cheap authenticated read per integration.
- Probe result rows retained under the existing retention classes; page
  reads the latest per integration (S15 seam).
- Failure → badge on `/admin/integrations` + structured WARN/ERROR log line
  (alert-greppable). No paging/email in v1.

## Acceptance — three-layer gate

- **① Technical:** probe job tests (success/failure/deadline); retry then
  dead-letter semantics inherited from S01.
- **② E2E (browser):** break one integration (bad token in a dev env) →
  badge appears within one probe cycle; screenshot.
- **③ Product (PAC):** PAC-7 badge leg.

## Out of scope

- Reconnect flows — **S17**. Alert channels beyond logs.
