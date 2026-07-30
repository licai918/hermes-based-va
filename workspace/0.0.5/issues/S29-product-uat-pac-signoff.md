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

- **~~The ② screenshot clause is unmet across the iteration~~ — DISCHARGED 2026-07-30, and the
  original reason was over-stated.** The narrow claim was correct: the **Browser pane** in this
  environment will not composite frames, so no slice could capture through it. The claim that
  followed — that screenshots were therefore impossible here — was never tested against **Chrome**,
  which composites fine. Screenshots exist: `../e2e-shots/` plus the owner-witnessed console
  captures. Slices are not marked down; the *controller's* generalisation is what was wrong.

  **The S02 review's visual-layer questions, answered off the live page rather than argued:**

  | S02 asked | measured on the running console |
  | --- | --- |
  | an 11-column table with an inline `<input>` | **13 columns**, intrinsic width **1992px**. Fits the 2040px viewport it was checked at; **does not fit 1440 or 1280**. Every ancestor is `overflow-x: visible`, so below ~2000px the **whole page** scrolls sideways rather than the table scrolling inside itself. Data stays reachable — this is ergonomics, not loss. **Unfixed and not in scope here; flagged.** |
  | is the red-bold `UNATTRIBUTED` badge legible, colour being its only visual channel | contrast **9.28:1** (`#8A1C1C` on `#FFFFFF`), bold, 16px — above WCAG **AAA** (7:1). And the premise was wrong: the badge is a distinct **word** beside `admin_manual`, so colour is emphasis, not the only channel. A colour-blind reviewer still reads it. |
  | is the PII footnote clipped | **not clipped** at the width checked (`scrollWidth == clientWidth`). Subject to the same sideways-scroll caveat below ~2000px. |
  | hit targets — the ~18px click offset that produced a *silent* no-op | **NOT re-tested.** Stated plainly rather than folded into the row above: nothing in this session exercised click accuracy, so that finding stands where S02 left it. |

  A frame also exposed **two defects no test had**: the seasonal row's forbidden wording, and four
  migration-seeded rows badged as though a named admin had approved them. Both fixed in this PR.
  That is the case for layer ② being a gate rather than a formality — **3,724 passing tests across
  all three suites** did not see either one.
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
