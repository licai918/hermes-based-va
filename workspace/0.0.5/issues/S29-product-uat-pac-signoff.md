# S29 — Product UAT + PAC sign-off (iteration close)

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** all — **OWNER-DRIVEN CLOSE** (gap-audit addition: 0.0.3 had S33, 0.0.4 had its
  UAT slice; 0.0.5 was missing its close)
- **Size:** S (coordination + fixes-found-here spawn their own follow-ups)
- **Depends on:** all tracks landed; S24 (the owner-input gate) complete
- **Delivers:** PAC-1..9 sign-off; the iteration's DONE definition
- **Surface:** owner-driven browser walkthrough; docs final state; CURRENT pointer

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D18** — the quality-feedback work folded into this branch's base carries two undischarged
  PAC items of its own: a human browser DOM pass over ReviewBar/thumbs/send-modal, and a
  simulator-driven PAC-1 subject (see `workspace/0.0.4/quality-feedback/PAC-CHECKLIST.md`).
  Folding qf into the 0.0.5 base makes them this sign-off's problem, not a thing already
  covered by 0.0.4's own close. List both explicitly as inherited items in the owner-driven
  walkthrough below, so they cannot ride along unnoticed as already signed off.

## ⚠ Carried exceptions — these do NOT get closed quietly (see [../DECISIONS.md](../DECISIONS.md))

- **The ② screenshot clause is unmet across the iteration, and it is an environment limitation,
  not negligence.** The Browser pane in this development environment will not composite frames,
  so no slice has been able to capture one. Three slices so far drove the real stack end to end
  and substituted page text, the accessibility tree, network calls and direct Postgres checks —
  stronger evidence than a screenshot for *behaviour*, and each one said plainly that it had no
  image rather than claiming otherwise.
  What only a rendered frame can verify is the **visual** layer, and the S02 review enumerated
  it concretely: an 11-column table with an inline `<input>` inside it; whether the red-bold
  UNATTRIBUTED badge is actually legible, given colour is its only visual channel; whether the
  PII footnote is clipped; and hit targets — the reported ~18px click offset that produced a
  *silent* no-op is direct evidence the visual layer is unverified.
  **Your walkthrough is where that gets discharged, for S01 and S02 together** (S01 had no human
  surface of its own and S02 is its console). Record it as an explicit exception carried and then
  closed, not as a gate that was always green.
- **Inherited from the quality-feedback merge**, per D18: a human browser DOM pass over the
  ReviewBar / thumbs / send-modal surfaces, and a simulator-driven PAC-1 subject. See
  `workspace/0.0.4/quality-feedback/PAC-CHECKLIST.md`.

## Goal

The owner walks every PAC scenario end-to-end on the real stack and signs the iteration off.
This is where "技术和产品都能通过" is proven for 0.0.5 as a whole — the three-layer gate's
③ layer, executed across tracks rather than per slice.

## Approach

- Owner-driven browser walkthrough of PAC-1..8 (the per-slice ② evidence exists; this pass is
  the OWNER witnessing the composed system): lexicon lifecycle (add→confirm→apply→retire),
  the three-notation retrieval, season confirm, value history, erase, blast-radius item,
  hub+inbox daily flow, latency tiles vs SLO, feedback loop closure, knowledge gate report.
- PAC-9 verification: CI replay gate + all governance tripwires green on the final composed
  branch; the whole-branch review (SDD convention) has run.
- Docs final state check: memory-layers.md shows L1-L7 all shipped with the decision tree,
  boundary rows, and forgetting table; ADRs landed with their slices (NFR-8 honored);
  `workspace/CURRENT` flips to 0.0.5-done / next-iteration pointer.
- Anything found here becomes named follow-up issues — the sign-off records them rather than
  silently absorbing them.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** final composed branch — full suites + replay gate + tripwires green.
- **② E2E (browser):** the owner-witnessed walkthrough, screenshots archived per PAC.
- **③ Product (PAC):** the owner signs PAC-1..9; open findings ledgered as follow-ups.

## Out of scope

- New features (findings become follow-up issues, not scope creep in the close).
