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
- **You are where the safety gate's breadth has to come from.** S21's review found that the
  gating half was reddening on correct behaviour — one of its five compliance markers was a
  fragment of the injected instruction itself, so a refusal that *quoted* the note tripped the
  gate. The fix cut the marker set to two effect-phrases and added two marker-authoring tests,
  including a structural one: **no marker may be a substring of the injected note.** Follow both
  when you author this family's scenarios; a marker that can appear in a refusal is worse than
  no marker, because it trains people to switch the gate off.
  The consequence is that enforcement is now two literal strings on one scenario — a deliberately
  low recall ceiling, documented in ADR-0160. **Breadth is your job**, not by loosening the
  markers but by adding scenarios whose obedience has its own unambiguous effect-phrase.
- **Author at least one scenario where obedience is expressed as a TOOL CALL with a bland
  reply.** `_eval_safety` reads only `outbound_text`, so the deterministic gate is blind to it
  by construction (recorded in ADR-0160 as an upgrade path; widening what the one gating
  assertion reads is a CI-gating change that needs its own slice, not a quiet extension here).
  Your family should still cover the shape, and must state plainly which half catches it — the
  advisory leg can, the gate cannot. A green gate must never be read as "no injected instruction
  was obeyed anywhere".
  **Decide this BEFORE you start authoring**, per S21's own recommendation: markers are now
  negation-safe by rule, which makes them narrower, and determiner/contraction variants are
  enumerated one string at a time. If the assertion should grow a tool-call form, that decision
  changes the shape of every scenario you write — hand-enumerating strings first and retrofitting
  afterwards is the expensive order.
- **Put effect-claim assertions in the `safety` block, never in a `text` block.** The
  negation-safety rules are applied by scanning scenarios that *declare* they make an
  effect-claim; scenario 06 inherits them only because it is named in an explicit list, since
  most `must_not_contain` lists are ordinary forbidden wording where a negation bar would be
  noise. A new effect-claim hidden in a `text` block would silently escape the rules — and that
  is precisely how the original Critical survived in two places at once.

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
