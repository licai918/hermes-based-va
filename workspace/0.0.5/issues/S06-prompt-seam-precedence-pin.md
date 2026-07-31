# S06 — Prompt seam: `<confirmed_lexicon>` glossary + cross-layer precedence + eval pin (+L7 ADR)

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T1 L7 Semantic Lexicon
- **Size:** M
- **Depends on:** S01 (S03 for meaningful content)
- **Delivers:** FR-6, FR-7
- **Surface:** render_injection composition; both turn paths; L7 ADR + memory-layers.md

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **⚠ THREE OTHER SLICES LEFT YOU INSTRUCTIONS AND THEY CONTRADICTED EACH OTHER.** A cross-slice
  audit found S06 is where three landed slices converge, each having recorded what it expected
  you to do — and the records disagreed. They are reconciled here; this list governs.
  1. **The ledger gate is PER-LAYER.** D4.1's original wording said to gate the injection-ledger
     write on the eval axis. That is now marked superseded, but read it: gating on the eval axis
     *alone* was the source of a real defect — L6's injection rides its own flag while the ledger
     rode a global memory flag, so a deployment with injection on and memory off recorded
     nothing. When you add the L7 seat (`injected_entry_refs(lexicon=…)`, already wired by S09 —
     both write sites need one extra kwarg, no table change), gate L7's ledger row on **L7's own
     injection flag**, not on a global one. Following the superseded wording reproduces the hole
     the fix just closed, one layer over.
  2. **You flip `memory-layers.md`'s L7 row from 🔬 exploring to shipped.** S02 noticed nothing
     owned it; your Approach does, in the same PR as the L7 ADR. It is genuinely yours.
  3. `injection_ledger.py`'s module comment names you as the slice that registers the lexicon
     flag. Consistent with (1) — just do not treat it as a second, separate instruction.
- **D16** — ship "newest-20" as a named module constant (e.g. `LEXICON_GLOSSARY_LIMIT = 20`),
  not a literal inline in the selection query. S22's knob panel, much later, must read this
  constant to render the glossary-N value; if it is a bare `20` buried in this slice, S22 has to
  go hunting for a magic number instead of importing a name. Define it once here, at the slice
  that first uses it.
- **D19 — you own the render-side fix for a live fence-escape injection surface.**
  `_render_memory` interpolates raw customer-authored slot values with no escaping, so a value
  containing `</untrusted_customer_memory>` closes the fence early and puts the rest of itself
  OUTSIDE the fence. S12's composition test passes anyway, because it only asserts that known
  content sits inside its fence; S12 has ledgered the gap and **this slice closes it**. Escape
  or strip fence-delimiter tokens at render time, and extend S12's composition test with the
  case it currently cannot catch: a slot value carrying a closing token must render with the
  fence structure intact. S01 hard-rejects these tokens on the write side; you are the defence
  in depth for values that predate that guard. Widening the test without fixing the renderer is
  not a fix.
- **D0** — "(S25 discipline)" in the Goal below means **S25-0.0.3**, as does the "two-flag
  precedent" in the Approach. Neither refers to the 0.0.5 S25.
- **D14** — the hit-ranked selection toggle that S26 later adds is flipped by a **deploy-time
  config commit**, not an in-app action; keep this slice's constant shaped so that reading it
  from config is a one-line change, and do not build an in-app mutation path.
- **L7 ADR carry-in:** redaction can change the *shape* of `proposer_context`, not just its
  content. A key that redacts to `[redacted]` when a sibling already redacted to the same string
  is suffixed (`[redacted] (2)`) rather than overwritten — dropping it would destroy governance
  evidence with no trace. That is an unspecified shape change today; **state it in the L7 ADR**,
  because S02 and S25 both read `proposer_context` and neither should key off its keys.
- **NFR-8 carry-in (found during the S12 fix):** `memory-layers.md` has **no row at all** for
  the ADR-0154 quality-feedback stores (`interaction_review`, `draft_feedback`) that arrived
  with the merged qf work. S12 declared their four `toee_feedback` actions as non-memory-writes
  because the map places them nowhere, but a reader would plausibly expect them next to "eval
  records" under L3. You are the next slice to edit that file, so **place them explicitly** —
  either as their own row or as an explicit statement that they sit outside the L1-L7 model —
  and make the `LAYER_OF_ACTION` declarations agree with whatever you decide.

## Goal

FR-6: bounded newest-20 confirmed entries rendered as a fenced `<confirmed_lexicon>` block on
both turns — fail-closed, default-OFF on the eval path (S25 discipline). FR-7 (grill-locked):
cross-layer render precedence — L4 carries override standing; `default_rule` text carries
"unless the customer's own preference says otherwise". US3's confirm behavior. Ships the
**L7 decision ADR** + memory-layers.md L7 row exploring→shipped (NFR-8).

## Approach

- `load_confirmed_lexicon(store)` mirror of `load_confirmed_experience` (bounded, fail-closed)
  behind **TWO independent default-OFF flags** — copilot + external, disable-able separately
  (gap-audit fix: locked now, the S25-0.0.3 two-flag precedent; recorded in the ADR).
- `render_injection` gains the lexicon block; composition order + precedence phrasing per the
  locked rule; **`default_rule` conditions are EVALUATED at render** (gap-audit fix — e.g.
  `current_season(date)` from S03 resolves which default applies; admin override row wins)
  and render with the confirm-required posture.
- Extend S12's composition test with the precedence assertion (FR-16 extension clause).
- Newest-20 now; the hit-ranked selection TOGGLE ships in **S26** (assigned, not orphaned).
- **memory-layers.md completion (gap-audit fix, NFR-8, same PR as the L7 ADR):** L7 row
  exploring→shipped, PLUS the L1-L7 routing decision tree and the L7 boundary-matrix rows
  from the exploration land in the map (the forgetting table lands with S22's ADR section).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** only confirmed entries render (proposed/rejected/retired excluded, both
  paths); flags default OFF on record/replay (replay suite green); load failure = skip, turn
  completes; precedence composition test green; L7 ADR file exists; memory-layers.md updated.
- **② E2E (browser):** with the flag on, a bare size in the current season draws the seasonal
  default AND a confirmation question; screenshot.
- **③ Product (PAC):** PAC-1's season/confirm leg.

## Out of scope

- Hit-ranked selection — post-S26. Effectiveness scores — **S26**.
