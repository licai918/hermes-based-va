# S33 — Product UAT: owner runs PAC-1…9 in the simulator; sign-off doc

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** Final — product gate, all tracks
- **Size:** M
- **Depends on:** ALL (S01–S32)
- **Delivers:** §6 product gate (PAC-1…9; PAC-10 signed at S32)
- **Surface:** owner-run PAC pass in the simulator + workbench; sign-off document

## Goal

The §6 product gate: the owner runs **PAC-1 through PAC-9** in the simulator
(knowledge, memory regression, propose→confirm, email+merge, supervisor view,
self-service, L6, measurement, hygiene), each per its §6 wording, and the
results are captured in a sign-off doc. PAC-10 was signed at S32. This closes
the iteration.

## Approach

- Owner-run pass over PAC-1…9 using the simulator controls (S03 page, S04
  presets/reset, S05 link identity, S18 channel switcher) and the admin/copilot
  surfaces the other slices created.
- PAC-2 explicitly re-proves the 0.0.1 memory behavior through the simulator
  (US10's regression guard).
- PAC numbers are iteration-scoped (0.0.3 PAC-n); cross-iteration references
  in the doc are qualified (audit finding 13).
- A failed scenario routes back to the owning slice; re-run after the fix — no
  new feature work lands in this slice.
- Sign-off doc records scenario, run evidence (screenshots), and the owner's
  verdict; exact form/location in workspace/0.0.3 is implementer's choice.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** the full suite is green on the final build at UAT time —
  slice suites, eval replay (ADR-0119), removal tripwire, CI Postgres gate.
- **② E2E (browser):** the PAC runs are themselves browser-driven; each of
  PAC-1…9 has screenshot evidence attached in the sign-off doc.
- **③ Product (PAC):** owner sign-off recorded for PAC-1…9 — this slice IS
  layer ③ for the iteration; all three layers green = 0.0.3 done.

## Out of scope

- PAC-10 / knowledge gate — **S32**.
- Fixes for failed scenarios — **reopen the owning slice**; live-channel smoke
  — a launch activity (RK-6).
