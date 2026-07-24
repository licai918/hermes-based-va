# S09 — Capture sent-as-is vs sent-edited at the governed send

- **Milestone:** 0.0.4 — quality-feedback (module)
- **Track:** T3 Internal draft feedback
- **Size:** M
- **Depends on:** S08 (write path); shares the route added in S07
- **Delivers:** FR-7, FR-9
- **Surface:** Copilot Gateway draft state, the governed send modal, the feedback
  BFF route's outcome branch

## Goal

Record the implicit outcome with **zero rep effort** and **zero risk to the
customer reply**.

## Approach — the plumbing this needs, and why

The scan of the current code found two gaps that make this more than a callback:

1. **No draft correlation id exists.** A draft is a plain mutable string in
   gateway state; neither the draft tool nor the chat draft-card response returns
   an id. Mint a client-side correlation id when a draft is produced (both
   entry points: the draft actions and a chat reply carrying a draft card).
2. **The send modal cannot see the original draft.** It receives only the
   possibly-edited body, because editing mutates the same state the modal is
   handed. Retain the **generated** body at generation time and pass it into the
   modal as a new prop, so the comparison has both sides.

Then, on a **successful** governed send only:

- Compare the sent text to the generated snapshot after trimming → `sent_as_is`
  or `sent_edited` plus a normalized edit-distance ratio.
- Call the feedback route's outcome branch **fire-and-forget**: failures are
  logged and swallowed, exactly like the existing metric emitter. Quality
  telemetry must never be able to break a customer reply — this is the one
  non-negotiable behaviour in the slice.

## Acceptance — three-layer gate

- **① Technical:** component tests — sending an untouched draft records
  `sent_as_is`; editing then sending records `sent_edited` with a ratio;
  whitespace-only difference still counts as as-is (trim boundary); **a failing
  outcome call does not fail the send, does not surface an error to the rep, and
  does not block the modal from closing**; no outcome is recorded when the send
  itself fails. Handler test for the route's outcome branch.
- **② E2E (browser):** in a claimed case with an active SMS session, send an
  untouched draft, then generate another, edit it, and send — confirm one
  `sent_as_is` and one `sent_edited` row with a plausible ratio. Screenshots.
- **③ Product (PAC):** PAC-4 — the owner drives a case to a draft in the
  simulator, thumbs-down it, edits it, sends it, and confirms the explicit rating
  and the `sent_edited` outcome share one correlation id.

## Out of scope

- **Email and internal-note drafts.** They leave by manual copy with no send
  event, so they carry explicit ratings only. Revisit if a governed email send
  ships.
- Any use of the ratio (thresholds, tiles, alerts) — Phase 2.
