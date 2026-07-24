# S10 — `list_feedback` read on the Supervisor Admin profile

- **Milestone:** 0.0.4 — quality-feedback (module)
- **Track:** T4 Supervisor read
- **Size:** S
- **Depends on:** S03 and S06 (both tables must exist)
- **Delivers:** FR-3 (read half), NFR-2
- **Surface:** mock + Postgres handler for `list_feedback`; no UI

## Goal

Give the Supervisor Admin profile a governed read over both feedback tables — the
seam Phase 2's aggregation will consume, and the one an admin can inspect through
dispatch today without a database client.

Shipping the read now, with the tables fresh, keeps Phase 2 from having to
re-open the tool surface later.

## Approach

- Read-only handler returning **Interaction Review** and **Draft Feedback** rows
  with bounded result sizes and a filter for unreviewed-since / verdict, keeping
  the shape aggregation-friendly (reason tags as first-class fields, not prose).
- Registered on the supervisor admin profile only, per S02's allowlist work.
- **Known and accepted seam — document it in the handler header:** profile
  allowlisting is **per tool, not per action**. Because `toee_feedback` is also
  in the internal copilot allowlist for the three write actions, `list_feedback`
  is *technically* dispatchable on that profile too. It is not reachable in
  practice because no copilot BFF route maps to it, and it is off the model
  surface via the agent-excluded set. The restriction is enforced by which route
  exists — record that, so a future reader does not mistake the allowlist for the
  boundary.

## Acceptance — three-layer gate

- **① Technical:** live-Postgres — reads back rows written by S03 and S06,
  including reason tags and the correlation id; bounded result size honoured;
  filters behave; an empty store returns an empty list, not an error. A test
  pins the documented per-tool allowlist consequence so the note cannot rot.
- **② E2E (browser):** carve-out — no UI in Phase 1.
- **③ Product (PAC):** none directly; enables Phase 2.

## Out of scope

- Aggregation, rates, dashboards, and proposal generation — **Phase 2**, which
  feeds the existing L6 review queue, the knowledge publish gate, and the metrics
  panel rather than building new surfaces.
- Any admin UI for browsing feedback.
