# 0.0.4 — Land all seven — issue slices

Fine-grained slices of [../PRD.md](../PRD.md) (7 tracks: API-only workbench,
durable Postgres job queue, TS cleanup, real integrations, integrations ops
surface, eval completion, metrics instrumentation). Each slice is
independently implementable and reviewable, names its own acceptance, and
carries the **three-layer gate** (0.0.3 convention): ① technical ② browser
E2E ③ owner PAC — with the pure-refactor carve-out where named.

**Numbering is iteration-scoped** (0.0.4 S-numbers). Precondition satisfied:
0.0.3 merged to main (PR #56, 2026-07-21).

## Dependency graph

```
T2 queue:  S01 queue core (+ADR) ─▶ S02 turn worker cutover ─▶ S03 outbound idempotency
           S01 ─▶ S04 background worker + trigger migration
           S03 ─▶ S05 dead-letter view + replay
T3 dead:   S06 zero-ref TS deletion   [independent — can land first]
T1 api:    S07 shared constants → packages/shared     S08 server-side account bootstrap
           S07 + S08 ─▶ S09 API-only cutover (delete stores/stubs + test migration)
           S02 + S04 + S09 ─▶ S10 one-command dev orchestration
T3 tail:   S07 + S09 ─▶ S11 delete domain-adapters + eval-runner (+API-only ADR)
T4 integ:  S12 Composio pin+cutover ─▶ S13 get_ar_summary real
           S14 EasyRoutes direct driver   [parallel to S12]
T5 ops:    S12 + S14 + S09 ─▶ S15 integrations status page ─▶ S17 reconnect (+integrations ADR)
           S04 + S15 ─▶ S16 scheduled health probes
T6 eval:   S02 ─▶ S18 live harness ─▶ S19 email suite in CI
           S18 ─▶ S20 judge advisory wiring (+live-eval ADR)
T7 meas:   S21 event counters   [independent]
           S04 + S20 ─▶ S22 honored-rate job      S20 ─▶ S23 quality-gates live
Final:     S24 product UAT + PAC sign-off (after ALL)
```

Execution order (grilled decision 19): **S01–S11 (substrate) → T4 → T5 →
T6 → T7 → S24.** Within the substrate: S01→S05 (queue) ‖ S06/S07/S08 first,
then S09 → S10/S11. S12/S14/S21 are parallel-safe anytime after their deps.

## Slices

| ID | Title | Size | Delivers |
| --- | --- | --- | --- |
| [S01](S01-job-queue-core.md) | Postgres job queue core + **queue ADR** | M | FR-7, FR-8, FR-14 |
| [S02](S02-turn-worker-cutover.md) | Turn worker cutover; delete `LocalDispatchingJobQueue` | M | FR-9 (turn), FR-10, NFR-1, NFR-2 |
| [S03](S03-outbound-idempotency.md) | Outbound send record + idempotency check | M | FR-12, NFR-3 |
| [S04](S04-background-worker.md) | Background worker + L6/retention/re-ingest trigger migration | M | FR-9 (bg), FR-11 |
| [S05](S05-dead-letter-view-replay.md) | Dead-letter workbench view + governed Replay | M | FR-13 |
| [S06](S06-zero-ref-ts-deletion.md) | Delete `services/hermes-gateway` + `packages/hermes-runtime` | XS | FR-15 |
| [S07](S07-shared-constants-move.md) | Move shared constants to `packages/shared` | S | FR-6 |
| [S08](S08-server-side-account-bootstrap.md) | Server-side account bootstrap + lockout parity | S | FR-2 |
| [S09](S09-api-only-cutover.md) | API-only cutover: delete stores/stubs; tests to HTTP seam | L | FR-1, FR-3, FR-4, NFR-4 |
| [S10](S10-one-command-dev-up.md) | One-command dev orchestration | M | FR-5, NFR-5 |
| [S11](S11-delete-ts-mock-packages.md) | Delete TS mock packages + **API-only ADR** | S | FR-16, FR-17 |
| [S12](S12-composio-pin-cutover.md) | Composio SDK pin + prod cutover of the 3 tools; delete `rest` shell | M | FR-18, FR-21, NFR-6, NFR-8 |
| [S13](S13-qbo-ar-summary-real.md) | QBO `get_ar_summary` real path | S | FR-19 |
| [S14](S14-easyroutes-direct-driver.md) | EasyRoutes direct driver (read-only delivery status) | M | FR-20, FR-21, NFR-6, NFR-8 |
| [S15](S15-integrations-status-page.md) | `/admin/integrations` status page | M | FR-23 |
| [S16](S16-scheduled-health-probes.md) | Scheduled integration health probes (queue job + badge) | S | FR-24 |
| [S17](S17-oauth-reconnect-flows.md) | In-app reconnect flows + **integrations ADR** | M | FR-25, FR-22 |
| [S18](S18-live-agent-harness.md) | Live agent eval harness (scripted + live modes) | M | FR-26 |
| [S19](S19-email-suite-ci.md) | Email suite transcripts + required CI replay gate | S | FR-27 |
| [S20](S20-judge-advisory-wiring.md) | Judge advisory wiring (every PR, real model) + **live-eval ADR** | M | FR-28, FR-29, NFR-7 |
| [S21](S21-event-counters.md) | Instrument `selfServiceUsage` + `l6ConfirmedEntries` | S | FR-30 |
| [S22](S22-honored-rate-job.md) | Honored-rate from a scheduled judge job | M | FR-31 |
| [S23](S23-quality-gates-live.md) | QualityGatesPanel reads live report artifacts | S | FR-32 |
| [S24](S24-product-uat-signoff.md) | Product UAT: owner runs PAC-1…9; sign-off | M | §7 product gate |

## Traceability — coverage check (no gaps)

**FR → slice:** FR-1→S09 · FR-2→S08 · FR-3→S09 · FR-4→S09 · FR-5→S10 ·
FR-6→S07 · FR-7→S01 · FR-8→S01 · FR-9→S02+S04 · FR-10→S02 · FR-11→S04 ·
FR-12→S03 · FR-13→S05 · FR-14→S01 · FR-15→S06 · FR-16→S11 · FR-17→S11 ·
FR-18→S12 · FR-19→S13 · FR-20→S14 · FR-21→S12+S14 · FR-22→S17 · FR-23→S15 ·
FR-24→S16 · FR-25→S17 · FR-26→S18 · FR-27→S19 · FR-28→S20 · FR-29→S20 ·
FR-30→S21 · FR-31→S22 · FR-32→S23.

**NFR → enforcement:** NFR-1/2→S02 · NFR-3→S02+S03 · NFR-4→S09 · NFR-5→S10 ·
NFR-6→S12+S14 (secret-scan gate) · NFR-7→S20 · NFR-8→S12+S14 (deadline
discipline).

**PAC → slice(s):** PAC-1→S08+S09+S10 · PAC-2→S02+S03 · PAC-3→S05 ·
PAC-4→S04 · PAC-5→S06+S10+S11 · PAC-6→S12+S13+S14 · PAC-7→S15+S16+S17 ·
PAC-8→S18+S19+S20 · PAC-9→S21+S22+S23 · all → S24 sign-off.

**User stories:** US1–2→S08/S09 · US3→S02 · US4→S03 · US5–6→S05 · US7→S04 ·
US8→S10 · US9→S09 · US10→S06+S11 · US11→S04 · US12→S14 · US13→S12+S13 ·
US14→S12+S14 (fail-closed) · US15→S15 · US16→S16 · US17→S17 · US18→S18 ·
US19→S20 · US20→S19 · US21→S21+S22 · US22→S23. **All 22 covered.**

**ADRs:** queue ADR rides S01 · API-only ADR rides S11 · integrations ADR
rides S17 · live-eval ADR rides S20.

**Coverage check result:** FR-1…FR-32 ✓ · NFR-1…NFR-8 ✓ · PAC-1…PAC-9 ✓ ·
US 1–22 ✓ · 4 ADRs assigned ✓. **No requirement is unslotted; no slice
delivers nothing.**
