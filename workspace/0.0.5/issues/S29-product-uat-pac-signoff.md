# S29 — Product UAT + PAC sign-off (iteration close)

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** all — **OWNER-DRIVEN CLOSE** (gap-audit addition: 0.0.3 had S33, 0.0.4 had its
  UAT slice; 0.0.5 was missing its close)
- **Size:** S (coordination + fixes-found-here spawn their own follow-ups)
- **Depends on:** all tracks landed; S24 (the owner-input gate) complete
- **Delivers:** PAC-1..9 sign-off; the iteration's DONE definition
- **Surface:** owner-driven browser walkthrough; docs final state; CURRENT pointer

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
