# S13 — S20 reversal: drop draft-turn write overlay; update tests + re-record eval artifacts; reversal ADR

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T3 Propose→confirm
- **Size:** M
- **Depends on:** none
- **Delivers:** FR-14, NFR-2, NFR-6, NFR-8 (reversal ADR)
- **Surface:** copilot draft turn profile (datastore write overlay); 0.0.2 test suites; eval recordings

## Goal

FR-14: "revert the draft turn's autonomous persist: the copilot draft turn no
longer receives the datastore overlay for `toee_customer_memory` writes (reads
stay governed)." The **S20-reversal ADR** ships with the build (RK-3: prevents
"why is this off" archaeology).

## Approach

- Drop the draft-turn write overlay; governed reads untouched.
- The 0.0.2 tests asserting the autonomous persist are **rewritten
  deliberately, not deleted** (RK-3).
- **Eval re-recording (audit finding 8):** recorded scenarios exercising the
  draft-turn write are re-recorded against the propose-only contract; the
  no-inferred-write eval stays green; recording sessions force mock backends
  (0.0.2 SECURITY discipline; NFR-6).
- The `resolve_memory_write_source` unit seam keeps `copilot_agent` — the
  resolver mapping is unchanged; production simply no longer routes writes
  through it.
- **ADR-0148 invariants must not break (NFR-2):** `source` /
  `actor_account_id` / binding keys stay framework-derived, never
  model-supplied; binding stays context-only; unresolvable identity still fails
  closed (`policy_blocked`); the removal tripwire stays green.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** rewritten unit + datastore tests (live Postgres): a draft
  turn that previously persisted now writes **nothing** to
  `toee_customer_memory`; the resolver seam still maps INTERNAL-without-user →
  `copilot_agent`; eval replay green on the re-recorded artifacts; removal
  tripwire green. Reversal ADR present.
- **② E2E (browser):** drive a copilot conversation whose draft infers a
  preference → the preferences panel shows **no** new slot; screenshot.
- **③ Product (PAC):** PAC-3's "no autonomous draft-turn persist exists" leg
  (full PAC after S15).

## Out of scope

- The `proposals[]` envelope — **S14**.
- Accept/Dismiss UI + governed Accept write — **S15**.
