# S15 — Proposal UI in preferences panel: Accept (governed dispatch write) / Dismiss; audit records

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T3 Propose→confirm
- **Size:** M
- **Depends on:** S14
- **Delivers:** FR-16, FR-17 (audit records)
- **Surface:** existing preferences panel; BFF `dispatchWrite` path; proposal audit records

## Goal

FR-16: "the existing preferences panel renders pending proposals with **Accept
/ Dismiss**. Accept routes through the **existing** governed dispatch write
(`upsert_preference`, actor-attributed → `employee_confirmed`). Dismiss
persists nothing." FR-17: "accepted/dismissed each leave an audit record
(proposal, origin, decider, timestamp)."

## Approach

- Render S14's `proposals[]` as pending items in the existing preferences panel.
- Accept = the existing governed dispatch write via BFF `dispatchWrite` with
  actor (§7 seam 5 — **no new write path**); `employee_confirmed` + actor
  attribution are framework-derived, one click for the rep (US16).
- Dismiss persists no slot — a bad guess cannot quietly persist (US17).
- Both outcomes write the FR-17 audit record (proposal, origin, decider,
  timestamp); storage placement within existing audit patterns is
  implementer's choice. Surfacing on the supervisor view is S16.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest: Accept → `dispatchWrite` payload with actor;
  Dismiss → no write call; both → audit record. Datastore integration (live
  Postgres): accepted slot persists `source=employee_confirmed` + actor;
  dismissed leaves no slot but an audit row — read back directly from Postgres.
- **② E2E (browser):** copilot conversation → proposals appear in the
  preferences panel → Accept one (slot appears, attributed), Dismiss another
  (no slot); screenshots.
- **③ Product (PAC):** PAC-3 — the owner runs the full propose→confirm loop
  (simulator customer side + workbench rep side), checks Accept attribution in
  the audit view and that Dismiss persists nothing.

## Out of scope

- Proposal-history section on the supervisor view — **S16**.
- The L6 review queue reusing this interaction pattern — **S24**.
