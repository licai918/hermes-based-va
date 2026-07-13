# 0.0.1 / M1 — Issue slices

Fine-grained slices of [../PRD.md](../PRD.md) (Customer Memory activation,
external + Copilot). Each slice is independently implementable and reviewable and
names its own acceptance. Build order follows the dependency graph.

## Dependency order

```
S01 ─▶ S02 ─┬─▶ S06 ─┬─▶ S07 ─▶ S09
            │        └─▶ S08
            ├─▶ S03 ──▶ (needs S04)
            ├─▶ S04 ─▶ S05
            └─▶ S10 ─▶ S11
S03/S02/S10 ─▶ S12 (datastore tests)
S04..S11    ─▶ S13 (E2E acceptance)
S07/S03/S10 ─▶ S14 (eval real-path + new scenarios)
all         ─▶ S15 (product UAT + sign-off)
```

Suggested sequence: S01 → S02 → S04 → S05 → S06 → S07 → S08 → S03 → S09 → S10 →
S11 → S12 → S14 → S13 → S15. (Write S12 tests alongside S02/S03/S10 TDD-style.)

## Slices

| ID | Title | Size | Delivers |
| --- | --- | --- | --- |
| [S01](S01-ingress-channel-identity-in-context.md) | Thread channel identity (E.164) into ingress context | S | FR-5 prereq, RK-3 |
| [S02](S02-binding-key-canonical-fail-closed.md) | Canonical binding key + fail-closed resolve | S | FR-5, R1, R6 |
| [S03](S03-write-discipline-hardening.md) | Write discipline: framework `source`, `evidence`, caps | M | FR-3, R4, RK-1 |
| [S04](S04-composite-driver-overlay.md) | Composite driver overlay (`extra_drivers`) | M | FR-2 |
| [S05](S05-graceful-degradation-no-db.md) | Graceful degradation without a datastore | S | FR-7, RK-6 |
| [S06](S06-store-load-customer-memory.md) | `load_customer_memory` in the gateway store | S | FR-1 (read base) |
| [S07](S07-read-injection-external-turn.md) | Read injection — external turn | M | FR-1 |
| [S08](S08-read-injection-copilot-turn.md) | Read injection — Copilot turn | M | FR-1 |
| [S09](S09-untrusted-memory-injection.md) | Injected memory treated as untrusted data | S | FR-6, RK-2 |
| [S10](S10-provisional-merge-async-idempotent.md) | Provisional→verified merge (async, idempotent, audited) | M | FR-4, R5, RK-5 |
| [S11](S11-turn-observability.md) | Turn observability: binding_key + slot names + merge-fired | S | §6.4 |
| [S12](S12-datastore-integration-tests.md) | Datastore integration tests (R1–R6) | M | §6.2, §6.3 |
| [S13](S13-e2e-acceptance-matrix.md) | E2E acceptance: matrix + isolation + merge + tripwire + degradation | L | §6.1, §6.0 |
| [S14](S14-eval-scenarios-real-path.md) | Eval 24–26 → real path; add 27/28/29 | M | §6.3, NFR-4 |
| [S15](S15-product-uat-signoff.md) | Product UAT + PAC-1…7 sign-off | M | §6.5, §6.6 product gate |

## Definition-of-Done coverage (traceability)

- §6.6 technical gate → S12 (unit/datastore) + S13 (E2E matrix, tripwire,
  degradation) + S14 (eval real path).
- §6.6 product gate → S15 (PAC-1…7, licai sign-off).
- Every FR-1…FR-7 maps to at least one slice above; RK-1/2/3/5/6 are folded into
  S03/S09/S01+S02/S10/S05 respectively.
