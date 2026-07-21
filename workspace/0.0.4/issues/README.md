# 0.0.4 — Durable substrate — issue slices

Fine-grained slices of [../PRD.md](../PRD.md) (3 tracks: durable Postgres job
queue, API-only workbench, TS cleanup). Each slice is independently
implementable and reviewable, names its own acceptance, and carries the
**three-layer gate** (0.0.3 convention): ① technical ② browser E2E ③ owner
PAC in the simulator — with the pure-refactor carve-out where named.

**Numbering is iteration-scoped** (0.0.4 S-numbers; each prior iteration had
its own list). **Precondition for ALL slices:** 0.0.3 merged to main (grilled
decision 11).

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
Final:     S12 product UAT + PAC sign-off (after ALL)
```

Suggested sequence: **S01→S05 (queue) and S06/S07/S08 in parallel first** →
S09 → S10/S11 → S12.

## Slices

| ID | Title | Size | Delivers |
| --- | --- | --- | --- |
| [S01](S01-job-queue-core.md) | Postgres job queue core: `job` table migration, claim/retry/dead/lease semantics; **queue ADR** | M | FR-7, FR-8, FR-14 |
| [S02](S02-turn-worker-cutover.md) | Turn worker cutover: fast-ack enqueues to Postgres; turn worker process; delete `LocalDispatchingJobQueue` | M | FR-9 (turn), FR-10, NFR-1, NFR-2 |
| [S03](S03-outbound-idempotency.md) | Outbound send record + idempotency check before every Textline POST | M | FR-12, NFR-3 |
| [S04](S04-background-worker.md) | Background worker + migrate L6 fork / retention / re-ingest triggers to enqueue | M | FR-9 (bg), FR-11 |
| [S05](S05-dead-letter-view-replay.md) | Dead-letter workbench view + governed, audited Replay | M | FR-13 |
| [S06](S06-zero-ref-ts-deletion.md) | Delete `services/hermes-gateway` + `packages/hermes-runtime` (+ dead dep line) | XS | FR-15 |
| [S07](S07-shared-constants-move.md) | Move workbench-needed constants from `@toee/domain-adapters` to `packages/shared` | S | FR-6 |
| [S08](S08-server-side-account-bootstrap.md) | Server-side dev account bootstrap + ADR-0018 lockout parity check | S | FR-2 |
| [S09](S09-api-only-cutover.md) | API-only cutover: delete 4 stores + seed + TS chat stub; fail-closed config; BFF tests to HTTP seam | L | FR-1, FR-3, FR-4, NFR-4 |
| [S10](S10-one-command-dev-up.md) | One-command dev orchestration (Postgres + dispatch servers + gateway + workers + workbench) | M | FR-5, NFR-5 |
| [S11](S11-delete-ts-mock-packages.md) | Delete `packages/domain-adapters` + `packages/eval-runner` (TS); workspace config; **API-only ADR** | S | FR-16, FR-17 |
| [S12](S12-product-uat-signoff.md) | Product UAT: owner runs PAC-1…5; sign-off doc | S | §7 product gate |

## Traceability — coverage check (no gaps)

**FR → slice:** FR-1→S09 · FR-2→S08 · FR-3→S09 · FR-4→S09 · FR-5→S10 ·
FR-6→S07 · FR-7→S01 · FR-8→S01 · FR-9→S02+S04 · FR-10→S02 · FR-11→S04 ·
FR-12→S03 · FR-13→S05 · FR-14→S01 · FR-15→S06 · FR-16→S11 · FR-17→S11.

**NFR → enforcement:** NFR-1→S02 (ack p95 before/after) · NFR-2→S02 (claim
latency) · NFR-3→S02+S03 (kill-worker drill) · NFR-4→S09 (CI on API-only) ·
NFR-5→S10.

**PAC → slice(s):** PAC-1→S08+S09+S10 · PAC-2→S02+S03 · PAC-3→S05 ·
PAC-4→S04 · PAC-5→S06+S10+S11 · all → S12 sign-off.

**User stories:** US1–2→S08/S09 · US3→S02 · US4→S03 · US5–6→S05 · US7→S04 ·
US8→S10 · US9→S09 · US10→S06+S11 · US11→S04. **All 11 covered.**

**ADRs:** queue ADR rides S01 (supersedes ADR-0105); API-only ADR rides S11
(retires Slice-2 dual-path).

**Coverage check result:** FR-1…FR-17 ✓ · NFR-1…NFR-5 ✓ · PAC-1…PAC-5 ✓ ·
US 1–11 ✓ · 2 ADRs assigned ✓. **No requirement is unslotted; no slice
delivers nothing.**
