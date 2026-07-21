# S31 — Debt XS pair: QBO link-check persona mirror + `_require_slot` consolidation

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T8 Hygiene
- **Size:** XS
- **Depends on:** none
- **Delivers:** FR-32, FR-33
- **Surface:** `_TOOL_PARAM_CONVENTIONS` (copilot persona); `_require_slot` helpers

## Goal

FR-32: "`_TOOL_PARAM_CONVENTIONS` documents the email-link-check workflow
(`get_email_link_status` → `linked` before `get_invoice`/`get_ar_summary`)."
FR-33: "`_require_slot` near-duplicate consolidation." Two XS tech-debt items,
paired into one slice.

## Approach

- Mirror the QBO link-check convention into `_TOOL_PARAM_CONVENTIONS` so the
  copilot side documents the workflow the tools already expect.
- Consolidate the `_require_slot` near-duplicates into a single helper —
  behavior identical; existing suites are the regression guard.
- No new behavior in either half; anything beyond the two named items is out.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** all existing suites green after the `_require_slot`
  consolidation; a unit/presence check asserts the QBO link-check convention
  text in `_TOOL_PARAM_CONVENTIONS`.
- **② E2E (browser):** **carve-out (NFR-1, audit finding 11): the
  `_require_slot` refactor half is a pure refactor with no behavior change —
  layer ① only; exemption named here.** For the mirror half: a copilot
  workbench conversation whose draft follows the link-check workflow
  (`get_email_link_status` before `get_invoice` in the turn's tool trace);
  screenshot.
- **③ Product (PAC):** no direct PAC scenario; regression cover rides S33.

## Out of scope

- Any behavior change to the QBO tools themselves.
- Broader persona/convention documentation beyond the named workflow.
