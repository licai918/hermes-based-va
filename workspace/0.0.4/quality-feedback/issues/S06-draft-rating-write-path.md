# S06 — Draft Feedback table + explicit rating write path

- **Milestone:** 0.0.4 — quality-feedback (module)
- **Track:** T3 Internal draft feedback
- **Size:** M
- **Depends on:** S02
- **Delivers:** FR-1, FR-2, FR-4, NFR-2, NFR-5
- **Surface:** migration (next free after S03's, re-checked at PR time); mock + Postgres handlers
  for `submit_draft_rating`; no UI

## Goal

Persist a rep's explicit judgment on one **Copilot Draft Action** draft —
thumbs-up, or thumbs-down carrying at least one internal **Review Reason Tag** —
actor-attributed and append-only.

## Approach

- Migration: `draft_feedback` table — case id, draft correlation id, draft kind
  (`sms` | `email` | `note`), the generated-draft snapshot, outcome
  (`sent_as_is` | `sent_edited` | `rated_only`), optional edit-distance ratio,
  optional verdict (`up` | `down`), reason tags, optional comment, rep account,
  created-at. A DB-level CHECK enforces that a `down` carries at least one tag.
  The table serves both this slice and S08's implicit outcome; this slice writes
  `rated_only` rows.
- Handler for `submit_draft_rating`, sharing the fail-closed actor resolver from
  S03 so both mechanisms enforce attribution identically.
- **Additional gate for this mechanism:** the acting rep must hold the case
  (mirror the existing claim-ownership predicate used by the governed send) —
  feedback on a case you do not own is refused.
- Validates: verdict in enum; `down` carries ≥1 tag; every tag belongs to the
  **internal** tag set (the external set is rejected here); draft kind in enum.
- Writes a Workbench Audit Log entry with a distinct action string in the same
  transaction.

## Acceptance — three-layer gate

- **① Technical:**
  - Live-Postgres: rating rows SELECTed back directly; append-only proven.
  - **No-actor governance test:** dispatch with no acting employee →
    `policy_blocked`, zero rows, no audit row.
  - Unclaimed-case test → `policy_blocked`, zero rows.
  - Rejections persist nothing: `down` without tags, an *external* tag, unknown
    draft kind.
  - Model-supplied actor/verdict in params ignored.
- **② E2E (browser):** carve-out — no UI yet.
- **③ Product (PAC):** feeds PAC-3 and PAC-5.

## Out of scope

- The implicit send outcome (`record_draft_outcome`) — **S08**; this slice ships
  the table it will also write to, but not that action.
- All UI — **S07**, **S09**.
