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

## PAC status after the 2026-07-30 walkthrough run (evidence, not assertion)

| PAC | state | basis |
| --- | --- | --- |
| **PAC-1** | ✅ **shown** (all-season window) | A bare **`185 55 16`** — an in-stock size — returned: *"We carry the **185/55R16** Grenlander Kingpro One **Passenger** tire … **Were you looking for passenger tires, or something else in that size?**"* Three things in one reply: the normalizer resolved the bare digits; the seasonal `default_rule` supplied the class; and it was rendered as a **QUESTION before quoting**, which is FR-7/US3's confirm-first rule. It also says **"passenger tires"**, not "all-season" — D28.1's wording fix in the sentence the rule itself generates. **Caveat:** the PAC's text says "in winter defaults to winter tires"; this ran on 2026-07-30, the all-season window, so the same mechanism was shown on the other branch. The winter branch needs a January date or a clock override. |
| **PAC-2** | ✅ **shown** | add → edit → retire driven through the console. New row rendered `admin_manual` + a named decider and **no** UNATTRIBUTED badge (the D28.2 flag discriminates); `(edited …)` appeared on edit; retire left `retired` with no action buttons. |
| **PAC-3** | ✅ **shown** (retire half) | Entry injected into a live turn, then retired → `blast_radius` item with `open_case_count: 1`. The **preference old→new history** and **whole-binding erase trail** halves were NOT exercised. |
| **PAC-4** | ⚠ **partial** | Adversarial eval family green — but **D24 says green is not proof no injection was obeyed** (the gate reads reply text; obedience as a tool call is invisible). The L4 hard-reject leg was not driven by hand. |
| **PAC-5** | ⚠ **partly shown** | Hub renders every claim honestly (5/5 + a PII-absence check); inbox now populates and renders decisions. **Re-classify, triage annotations, NL pre-fill and the fail-review one-click L4 correction were NOT exercised.** |
| **PAC-6** | ⚠ **number in doubt** | Tiles live, 150 ms line shown — but L5 measured **p95 787.52 ms against its 800 ms budget** (98%) while the FR-7b gate reports 11.54 ms for the same code. Gate warms and loops; a turn does not. See the ⚠ in the walkthrough. |
| **PAC-7** | ⚠ **first clause shown, second clause structurally out of reach in one sitting** | Three `tone_inappropriate` fails submitted through the real review UI on three DISTINCT records → aggregator: `signals 11, clusters 5, tripped 1, emitted 1`. **ONE** proposal, not three, carrying `{"emitted_by":"feedback_aggregator","distinct_subjects":3,"signal_rows":3,"feedback_cluster":"tone_inappropriate"}`. Acknowledged it: queue 2 → 1. **The loop-closure metrics did not move, and that is correct** — see below. |
| **PAC-8** | 🔒 **owner** | 81% is real, and the questions AND their expected source pages were derived by the implementer from the owner's transcript. Read the 21 questions, not the percentage. |
| **PAC-9** | ⚠ **head drift** | CI 6/6 green on `ead07c2`; commits after that are unverified until pushed. |

**Nothing here is signed. This table is what a walkthrough produced, not a verdict.**

### PAC-7, what was established and what is missing

The **mechanism** was verified against the live database by running S25's real
`aggregate_feedback` (not a test double):

* `SAME_TAG_FAIL_THRESHOLD = 3`, counted in **DISTINCT SUBJECTS** — the same case reviewed three
  times is one problem, by design.
* Which tags can produce an inbox item at all: **tone** tags (`wrong_tone`, `too_verbose`,
  `tone_inappropriate`) → a `persona_review` item; **action** tags (`tool_misuse`, `wrong_action`,
  `should_have_escalated`) → an L6 procedure proposal. The **knowledge** tags emit nothing — that is
  D23's "five of eleven tags have nowhere legal to emit", and it is why the tag chosen for this PAC
  matters.
* The run reported `signals=8, clusters=0`. That looked wrong and is not: `aggregate_feedback`
  returns early when nothing is newer than its **watermark** (D13's idempotence leg), and the early
  return leaves `clusters` at its default. Confirmed by reading the function after observing the
  number, rather than filed as a defect.

**What is missing is the INPUT.** The database holds two failing reviews, both carrying
`['factual_error', 'should_have_escalated']`, and all of it sits behind the watermark. PAC-7 needs
**three distinct subjects failing on one tag, newer than the last run**. Creating that honestly means
a supervisor submitting three reviews through `/copilot/audit/auto-handled/<id>` — a governed write
that requires a supervisor session, which cannot be minted from outside (ADR-0093, HttpOnly signed
cookie).

**RUN 2026-07-30 with the owner signed in.** Three `tone_inappropriate` fails submitted through the
real review UI on three distinct auto-handled records. Aggregator:

```
signals 11   clusters 5   tripped 1   emitted 1   already_open 0   blocked 0   unrouted 0
```

**ONE proposal from three fails** — the PAC's central claim — carrying its own provenance:
`{"emitted_by":"feedback_aggregator","feedback_cluster":"tone_inappropriate","distinct_subjects":3,
"signal_rows":3,"window_days":30}`. Acknowledged: queue 2 → 1.

### The second clause did NOT happen, and that is the correct behaviour

Loop-closure metrics, measured immediately before and immediately after the acknowledge —
**identical**:

| metric | before | after |
| --- | --- | --- |
| Feedback that became a proposal (routable signals) | 33.3% — 3/9 | 33.3% — 3/9 |
| Feedback with nowhere legal to go (D23) | 18.2% — 2/11 | 18.2% — 2/11 |
| Confirmed fixes that came back | Not yet computed — 0/0 | Not yet computed — 0/0 |
| Edited L7 entries that held or improved honored rate | Not yet computed — 0/0 | Not yet computed — 0/0 |

The first two **had already moved** — from the aggregator run, not the acknowledge: the 3/9 IS this
cluster converting.

The last two cannot move on an acknowledge, by design. A `persona_review` item is **advisory**; the
routing table says a persona changes by *dev edit + eval re-record*, and acknowledge/dismiss are its
only actuators. "Confirmed fixes that came back" needs a CONFIRMED memory fix plus **judged turns
after it**; "edited L7 entries that held their honored rate" needs an EDIT plus judge scores.

**So PAC-7's second clause spans a loop no walkthrough can close in one sitting:** it needs an
ACTION-tag cluster (→ an L6 procedure proposal, not a persona item) → confirm → subsequent customer
traffic → the judge scoring it. That is days of real usage, not a session. **Stated as a limit of
the PAC as written**, not marked done and not marked broken.

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
