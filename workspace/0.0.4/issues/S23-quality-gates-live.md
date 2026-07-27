# S23 — QualityGatesPanel reads live report artifacts

- **Milestone:** 0.0.4 — land all seven
- **Track:** T7 Metrics instrumentation
- **Size:** S
- **Depends on:** S20 (report artifacts exist)
- **Delivers:** FR-32
- **Surface:** admin API read + `QualityGatesPanel.tsx`

## Goal

FR-32: the panel's hand-copied static numbers are replaced by the latest
actual recall/judge report artifacts, with timestamp + provenance shown.

## Approach

- Persist/locate the latest gate reports (knowledge recall harness output +
  S20 judge reports) behind a governed admin read; panel renders values +
  "as of" + source run link.
- Stale-report honesty: if the newest report is older than a threshold, the
  panel says so rather than presenting it as current.

## Acceptance — three-layer gate

- **① Technical:** read-path tests incl. no-report and stale-report states.
- **② E2E (browser):** panel shows the latest real numbers with timestamp;
  screenshot matches the report artifact.
- **③ Product (PAC):** PAC-9 cross-check leg.

## Out of scope

- New gate types; report format changes.
