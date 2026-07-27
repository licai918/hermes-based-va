# S23 — Eval scenario families: preference-change / adversarial / deletion

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop
- **Size:** M
- **Depends on:** S21 (legs), S08 (hard-reject expected)
- **Delivers:** FR-29
- **Surface:** eval suites (recorded/replayed under the deterministic gate)

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **The stale-use leg can only see WITHIN-transcript supersession — say so, do not let the
  metric imply more.** S21 shipped that leg calibrated but flagged it as having nothing to
  detect in production, and the precise reason matters: the composer renders a slot's *current*
  value only, so the judge can catch "the customer changed their mind earlier in this thread and
  the agent still used the old value" — which your preference-change family exercises directly —
  but it is blind to supersession that happened in an earlier session, because nothing puts L4
  value history in front of the judge. S07 is landing that history in the audit trail; **surfacing
  it to the judge is not in any 0.0.5 slice.** Your family documentation and any panel copy must
  state which of the two the leg actually covers, so a green stale-use number is never read as
  "no stale memory was used anywhere". If you conclude the cross-session case is cheap to cover
  here, say so in your report rather than silently widening scope.
- **D0** — "the S09-0.0.2 unit tests" in the Goal below means the **0.0.2** slice's tests, not
  the 0.0.5 S09.

## Goal

FR-29 (C5 §5.8; "hit rate alone misleads" codified): three scenario families join the eval
suite — **preference-change** (state A, later state B → B honored AND A not used; exercises
the stale-use leg), **adversarial** (the S09-0.0.2 unit tests promoted to eval scenarios;
injection strings in customer text → not stored (S08) OR stored-but-not-obeyed, judged by the
GATING safety leg), **deletion** (forget-me → deflection + emptiness). US6's eval half.

## Approach

- Author scenarios in the existing recorded/replay format (scripted_eval_turn harness);
  deterministic by construction; judge legs attached per family.
- Adversarial family severity: safety-leg red = failed_high (gates CI); other legs advisory.
- Family membership documented so S24's knowledge gate and these families report as distinct
  suites (no conflation).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** all three families recorded + replaying green in CI; the adversarial
  family proven RED-capable (a deliberately-broken fixture flips it, then removed); replay
  determinism intact across the whole suite.
- **② E2E:** carve-out — eval-suite slice, ① only.
- **③ Product (PAC):** PAC-4's eval leg; feeds PAC-9.

## Out of scope

- The knowledge recall gate — **S24**. Live-traffic sampling (the scheduled judge job covers
  it).
