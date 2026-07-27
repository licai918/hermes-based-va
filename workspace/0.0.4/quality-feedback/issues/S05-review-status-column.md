# S05 — Reviewed / Not-reviewed status column on the audit lists

- **Milestone:** 0.0.4 — quality-feedback (module)
- **Track:** T2 External interaction review
- **Size:** M
- **Depends on:** S03 (table + read); E2E needs S04 to produce data
- **Delivers:** FR-6
- **Surface:** audit list reads (datastore handlers + workbench wire types) and
  both audit **list** views

## Goal

Make sampling coverage visible: a supervisor can see at a glance which
auto-handled records and sales-outreach cases have already been reviewed, so the
same conversation is not re-checked while others are never sampled.

**This is not a UI-only change.** The audit list rows carry no review state
today, so the list reads must surface it — that backend dependency is why this is
its own slice rather than a bolt-on to S04.

## Approach

- Extend the two audit **list** reads to surface a review-state field per row,
  derived from the latest review for that subject.
- **Semantics to implement (settled):** the badge means *any* review exists for
  the subject, by any reviewer — it answers "has this been sampled", not "did
  *I* review it". Because reviews are append-only, the read resolves the latest
  review per subject.
- Add the field to the workbench wire types for the auto-handled record and the
  case row.
- Add a status column to both audit list views, following the existing column and
  style conventions.

## Acceptance — three-layer gate

- **① Technical:** handler tests — a subject with no review reads not-reviewed;
  one review reads reviewed; two appended reviews still read reviewed and resolve
  to the latest. Component tests — the column renders both states. Live-Postgres
  coverage for the list read.
- **② E2E (browser):** submit a review on a detail view (S04), return to the list,
  and see the row flip to Reviewed. Screenshots.
- **③ Product (PAC):** PAC-2 — after PAC-1's fail verdict, the owner sees that
  record marked Reviewed in the list and an unsampled sibling still Not reviewed.

## Out of scope

- Filtering or sorting by review state, and any reviewer-attribution column —
  not requested; add only if sampling practice asks for it.
- Counts, rates, or any aggregate tile — Phase 2.
