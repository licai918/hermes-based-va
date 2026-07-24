# S03 — Interaction Review write path: table, gate, handlers

- **Milestone:** 0.0.4 — quality-feedback (module)
- **Track:** T2 External interaction review
- **Size:** M
- **Depends on:** S02
- **Delivers:** FR-1, FR-2, FR-4, NFR-2, NFR-5
- **Surface:** migration `0016`; mock + Postgres handlers for
  `submit_interaction_review`; no UI

## Goal

Persist an **Interaction Review** — a supervisor's pass/fail judgment on one
**Auto-Handled Interaction** record or one `sales_outreach` **Follow-up Case** —
through the governed dispatch path, actor-attributed and append-only.

This is the slice where the module's central governance claim becomes real and
testable: **a write with no framework-resolved acting employee persists
nothing.**

## Approach

- Migration `0016`: `interaction_review` table — subject kind
  (`auto_handled_record` | `sales_outreach_case`), subject id, verdict
  (`pass` | `fail`), reason tags, optional comment, reviewer account, created-at.
  A DB-level CHECK enforces that a `fail` carries at least one tag. Append-only:
  no UPDATE path; re-review inserts a new row. Index supports latest-per-subject
  reads. Follow the house style for a never-before-shipped number (bare
  `CREATE TABLE`, no `IF NOT EXISTS`).
- Shared resolver (imported by both the mock and Postgres handlers so the twins
  cannot drift) that derives the actor from the execution context and **fails
  closed** when absent, mirroring the existing agent-experience authorization
  resolver.
- Handler validates: verdict in enum; `fail` carries ≥1 tag; every tag belongs to
  the **external** Review Reason Tag set; subject kind in enum. Writes the row and
  a **Workbench Audit Log** entry with a distinct action string, in the same
  transaction.
- Verdict, reviewer, and tags are read from context/params per the framework
  contract — a model-supplied actor or verdict inside params is ignored.

## Acceptance — three-layer gate

- **① Technical:**
  - Live-Postgres: each write SELECTed back directly (not trusted from the tool
    return); append-only proven — two reviews by one reviewer yield two rows and
    the read resolves latest-wins.
  - **No-actor governance test:** dispatch with no acting employee →
    `policy_blocked` **and** zero rows **and** no audit row. This is the
    "AI cannot score itself" guarantee — assert absence, not just the error.
  - Rejections persist nothing: `fail` without tags, a tag from the *internal*
    set, an unknown subject kind — each a validation error with zero rows.
  - Model-supplied actor/verdict inside params is ignored (persisted row carries
    the framework-derived values).
- **② E2E (browser):** carve-out — no UI yet; the dispatch path is exercised by ①.
- **③ Product (PAC):** feeds PAC-1 and PAC-5.

## Out of scope

- The review bar UI and its BFF route — **S04**.
- The Reviewed/Not-reviewed list column — **S05**.
- Draft feedback (the other mechanism) — **S06+**.
