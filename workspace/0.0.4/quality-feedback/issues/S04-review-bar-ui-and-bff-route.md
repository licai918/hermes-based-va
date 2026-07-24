# S04 — Review bar on the audit detail pages + review BFF route

- **Milestone:** 0.0.4 — quality-feedback (module)
- **Track:** T2 External interaction review
- **Size:** M
- **Depends on:** S03
- **Delivers:** FR-5, FR-10
- **Surface:** `POST /api/copilot/audit/review` + Copilot BFF handler; review bar
  on the Auto-Handled and Sales Outreach **detail** views

## Goal

Give a **Workbench Supervisor** or **Workbench Admin** a one-click pass and a
guided fail on the two audit detail views, without changing the read-only stance
of those views toward conversation data.

## Approach

- New BFF handler in the Copilot BFF taking the request, the per-session API
  client, and the session; validates the body, then performs a governed write
  through the dispatch client so the acting employee rides along automatically.
- Route file exports `POST` alongside the existing audit reads and runs on the
  Node runtime, matching every other Copilot route.
- **Role enforcement note (verify, do not assume):** `/api/copilot/audit/*` is
  already supervisor-or-admin gated by the session wrapper's route-prefix access
  check. The datastore carries no role column, so the Python layer cannot
  distinguish a supervisor from a rep — the role boundary for this write lives
  at the BFF prefix gate. The slice must include a test proving a rep is refused,
  so this is verified rather than assumed.
- Review bar mounts below the summary header on both detail views: **Pass** is
  one click; **Fail** expands the external reason-tag chips (multi-select) plus
  an optional comment and a submit. An existing review by the current account
  renders its verdict and tags with an edit affordance that appends a new row.
- Both detail views are client components fetching through the shared async hook;
  the bar follows the same loading/error conventions and the shared style
  helpers.

## Acceptance — three-layer gate

- **① Technical:** handler tests against a faked transport asserting the
  dispatched envelope (tool, action, params) and that the actor is attached;
  role test — a rep session is refused; validation tests — fail without tags →
  400, foreign tag → 400. Component tests — unreviewed / reviewed / fail-expanded
  / rep-hidden states, and that submitting calls the injected callback with the
  verdict and tags.
- **② E2E (browser):** on each of the two audit detail routes, submit a pass and
  a fail-with-tags; the bar reflects the recorded verdict on reload; a Workbench
  Audit Log entry exists for the submit. Screenshots.
- **③ Product (PAC):** PAC-1 — in the Conversation Simulator, drive a
  conversation that auto-handles, open it in the audit view, score it fail with
  tags, and confirm the row and the audit entry.

## Out of scope

- The Reviewed/Not-reviewed column on the audit **lists** — **S05**.
- Any aggregation, dashboard, or Phase-2 proposal surface.
