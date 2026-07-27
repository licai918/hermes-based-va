# S17 — Prefills: NL manual-add + fail-review L4 correction

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T4 Memory-ops UX
- **Size:** S
- **Depends on:** S02 (manual-add form); qf Phase 1 (fail-review UI)
- **Delivers:** FR-24, FR-25
- **Surface:** two prefill affordances (copilot drafts, human confirms)

## Goal

FR-24: an admin types free text ("TOEE 也叫拓意") → the copilot drafts the structured lexicon
entry → the S02 manual-add form PRE-FILLS → the admin confirms. FR-25 (owner decision ⑦): a
supervisor fail-review with a preference-shaped cause offers a one-click PREFILLED L4
correction in the Memory Audit console. Copilot drafts, human writes — never the reverse.
US11/US12.

## Approach

- NL prefill: a small draft endpoint (internal profile, no memory writes — output is form
  JSON only); the form opens pre-filled; submission goes through the EXISTING manual-add
  governed action unchanged.
- Fail-review prefill: when a qf fail-review's reason/tag is preference-shaped, render a
  "correct preference" link that opens Memory Audit with slot+value prefilled from the review
  context; submission = the EXISTING correction path (`employee_confirmed`).
- Both are pure UX sugar over existing governed writes — zero new write paths (NFR-3).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest — NL draft returns valid form JSON for alias-ish text and a clear
  "couldn't parse" for junk (no silent guess); fail-review link carries the right prefill;
  submissions hit the existing actions with framework attribution; tsc clean.
- **② E2E (browser):** type the Chinese alias sentence → confirm → confirmed entry exists;
  fail a seeded review → one click → corrected slot with `employee_confirmed`; screenshots.
- **③ Product (PAC):** PAC-5's prefill legs.

## Out of scope

- Auto-submit of either prefill (human confirms, always).
