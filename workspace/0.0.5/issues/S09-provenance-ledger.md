# S09 — Injection provenance ledger (new table, both turn paths)

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T2 Lifecycle core
- **Size:** M
- **Depends on:** none
- **Delivers:** FR-11
- **Surface:** new migration; both turn paths (openrouter + copilot_turn)

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D1** — migration prefix **0021**.
- **D4.1 — the gate is the EVAL axis, not the injection axis.** The Approach below says "gate on
  the same axes the injections themselves are gated on" AND "never on the record/replay path".
  Those are different axes: `eval_record.py` **does** call `render_injection` with a scenario
  memory preset, so obeying the first clause literally writes ledger rows during record and
  breaks the replay gate inside this slice's own acceptance. Gate explicitly on **"not an eval
  path"** (the way the existing eval-neutral emits are gated), and additionally skip when
  nothing was injected.
- **D4.2 — do NOT write from `render_injection`.** It is a pure, store-less function in the
  plugin package with three callers (`openrouter.py`, `copilot_turn.py`, `eval_record.py`).
  Putting DB I/O in or around it is a layering violation that drags a DB dependency into the
  eval-record path. **Write from the callers**, with an explicit injected-entry-ref list.
- **D4.3 — `entry_ref` is a stable natural key, not a row id**: `binding_key + slot_name` for
  L4, entry id for L6/L7. The cross-channel merge path DELETEs and re-INSERTs L4 rows with new
  ids, so a row id would silently break S10's blast-radius join and S26's per-entry score.
- **D12** — your prune window and S20's zero-hit window are coupled. Both are named constants
  and **`prune_window >= zero_hit_window`** must be asserted in a test. If the prune window is
  shorter, garbage collection silently manufactures retirement candidates for entries that are
  actively in use.
- **D15** — this slice's ①-only carve-out is accepted (the ledger has no human surface until
  S10) but must be declared; the README's NFR-1 audit now names S09 alongside S12/S21/S23.

## Goal

FR-11 (closes verified gap 3; `agent_turn_trace` is NOT on main — this is its OWN table): per
governed turn, record WHICH memory entries were injected — turn/case ref × layer × entry
id/slot. The grain MUST support the turn×layer×entry join (C6 §6.6 clause) — this table is
both the blast-radius locator (S10) AND the effectiveness-score locator (S26).

## Goal-shaping constraints

- **Eval-neutral + fail-open (NFR-4/5):** ledger writes are fire-and-forget side effects that
  never touch `{final_response, messages}`, never raise into the turn, and never occur on the
  record/replay path (gate on the same axes the injections themselves are gated on — no
  injection, no row).
- Rows carry NO memory VALUES (ids/slots only — the content lives in its layer; no PII copy).

## Approach

- Migration (~002x, re-verify): `injection_ledger(id, turn_ref, case_or_binding_ref, layer,
  entry_ref, injected_at)` + the query indexes S10/S26 need.
- Write sites: everywhere `render_injection` composes content — L4 slots, L6 entries, L7
  entries (when S06 lands; additive) — one batched insert per turn.
- **Retention (gap-audit fix — the ledger grows per turn, unbounded is not an option):** ship
  a pruning path IN this slice — a windowed DELETE job on the scheduled-worker pattern (window
  a named constant, long enough for S10/S26 joins — e.g. ≥ the judge-sampling horizon), with
  last-run visibility alongside the existing sweep surfaces.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** live-PG — a turn with L4+L6 injections writes matching rows (grain proven
  by a join test); a no-injection turn writes none; ledger-write failure leaves the turn
  result intact; record/replay path writes nothing (replay suite green).
- **② E2E (browser):** carve-out — data-plumbing slice, ① only; surfaced to humans at S10.
- **③ Product (PAC):** feeds PAC-3 at S10.

## Out of scope

- Affected-cases query + review items — **S10**. Effectiveness join — **S26**.
