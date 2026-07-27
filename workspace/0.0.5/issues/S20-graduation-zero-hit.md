# S20 — Graduation sweep + zero-hit retirement feed

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T3 Boundary enforcement
- **Size:** M
- **Depends on:** S01, S15
- **Delivers:** FR-19, FR-20
- **Surface:** scheduled job (S04-0.0.4 worker pattern); inbox item kinds

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D9** — the retirement item you emit uses the `kind` value `retirement_candidate` (S15's
  `review_item.kind` enum is corrected to include it — see S15's own corrections block). Do not
  emit a hyphenated `retirement-candidate` or any other spelling.
- **D12** — your zero-hit window and S09's ledger prune window are coupled: if the ledger is
  pruned before your zero-hit window elapses, garbage collection silently manufactures
  retirement candidates for entries that are actually in active use. Both windows must be named
  constants, and a test must assert `prune_window >= zero_hit_window` so the relation breaks
  loudly if either constant is edited without the other.
- **D13** — "job failure leaves queues clean" (Acceptance below) does not mean transactional
  rollback — each propose dispatch is its own transaction and no compensating path exists.
  "Clean" means idempotent-on-retry via the watermark. A propose call that returns
  `policy_blocked` (routine — a candidate's evidence carrying a name or phone will trigger this)
  must be swallowed and counted into a metric; it must never fail the job and must never
  silently vanish. Test both behaviors explicitly.
- **D6** — "L7 usage = hit_count + ledger usage" means reading the MATERIALIZED `hit_count`
  column (S05's scheduled rollup, migration 0026) — never computing a count in-turn or
  re-deriving it from raw hit events here. This job reads two already-materialized numbers and
  sums them.

## Goal

Tier-4 enforcement (C4, grill-locked: SCHEDULED, not event-driven). FR-19: a sweep flags
confirmed L6 notes that are structurable (the S13 heuristic re-applied to CONFIRMED rows) as
"graduate to L7?" inbox items. FR-20: zero-hit entries (L7 hit_count / L6 usage over a
window) surface as retirement candidates — the free-text catch-all drains routinely into the
structured layer, dead vocabulary retires instead of accumulating. US16/US17.

## Approach

- One scheduled job, watermarked, propose-only (NFR-3): emits graduation + retirement items
  into the **S15 `review_item` store** (kinds graduation / retirement-candidate) with the
  entry + evidence; deciding them uses S15's existing actions (graduation Accept ≈
  Re-classify L6→L7 — which runs THROUGH the governed propose/decide actions, scans applying;
  retirement Accept = the existing retire).
- Window + thresholds are named constants (calibratable). **L7 usage = `hit_count`
  (deterministic applications, S05) + ledger-derived glossary usage (S09)** — count BOTH
  before calling an entry zero-hit (gap-audit fix); zero-hit merges into S26's entry-health
  score once that lands (this slice ships the usage-only version, honestly labeled).
- Sweep visibility: last-run + counts on the retention/hub surfaces (S28-0.0.3 pattern).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** live-PG — a seeded structurable confirmed L6 note yields ONE graduation
  item (idempotent across runs); a zero-hit L7 entry past the window yields a retirement item;
  in-window/active entries yield nothing; job failure leaves queues clean.
- **② E2E (browser):** run the sweep → both item kinds appear in the inbox; accept a
  graduation → the L7 entry exists and the L6 note is re-filed; screenshots.
- **③ Product (PAC):** feeds PAC-5/PAC-9.

## Out of scope

- Effectiveness-scored retirement — **S26** upgrades the feed. Auto-graduation (forbidden).
