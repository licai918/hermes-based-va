# S07 — Thumbs rating on the draft card + feedback BFF route

- **Milestone:** 0.0.4 — quality-feedback (module)
- **Track:** T3 Internal draft feedback
- **Size:** M
- **Depends on:** S06
- **Delivers:** FR-8, FR-10
- **Surface:** `POST /api/copilot/feedback` + Copilot BFF handler; the draft card
  in the Copilot Gateway

## Goal

Let a rep say *this draft was good* or *this draft was wrong, and here is why* in
one or two clicks, without ever slowing down customer work.

## Approach

- New BFF handler and route for feedback writes. The route sits under
  `/api/copilot/` but **not** under `/api/copilot/audit/`, so by the session
  wrapper's prefix rules it is open to any authenticated workbench user — which
  is correct here: reps are the intended authors. No in-handler role gate.
- The request body discriminates the feedback kind; this slice implements the
  explicit-rating branch and dispatches `submit_draft_rating`. S09 adds the
  outcome branch to the same route.
- Thumbs-up / thumbs-down mount on the draft card in the Copilot Gateway.
  Thumbs-down expands the internal reason-tag chips plus an optional comment.
- **Rating never blocks drafting or sending** — it is an adjacent control, not a
  step in the send flow, and a failed rating surfaces an inline error without
  touching the draft.
- The draft correlation id minted in S09 is shared: if S09 has landed, the rating
  carries the same id as the outcome row for that draft. Land whichever comes
  first and thread the id from the other.

## Acceptance — three-layer gate

- **① Technical:** handler tests against a faked transport asserting the
  dispatched envelope and attached actor; validation — thumbs-down without a tag
  → 400, external tag → 400. Component tests — thumbs-up submits immediately;
  thumbs-down expands tags and submits verdict + tags; a rating failure shows an
  error and leaves the draft editable and sendable.
- **② E2E (browser):** in a claimed case, generate a draft, thumbs-down with a
  tag, and confirm the row lands; then generate another and thumbs-up.
  Screenshots.
- **③ Product (PAC):** PAC-3 — the owner drives a case to a copilot draft in the
  simulator, rates it down with a tag, and sees the recorded row.

## Out of scope

- Implicit send-outcome capture and the correlation id / original-body plumbing —
  **S09**.
- Rating anything other than a draft (no rating on chat replies or case notes).
