# S03 — Simulator page + nav entry (thread view, composer, role gating)

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T2 Conversation Simulator
- **Size:** M
- **Depends on:** S02
- **Delivers:** FR-8, FR-12 (case link rides here per README traceability)
- **Surface:** workbench front end — new Simulator page under the authenticated copilot route group

## Goal

FR-8: "a workbench Simulator page + nav entry: conversation thread view,
message composer, identity/channel controls. Route-group and role-gating
consistent with ADR-0093." FR-12: a link from the simulated conversation to its
Human Intervention Case in the real copilot workbench — the copilot UI *is* the
employee simulator; no parallel UI.

## Approach

- New page + nav entry under the authenticated copilot group (§7 seam 7,
  ADR-0093 route-derived profiles).
- Thread view renders customer sends and agent replies read back through S02's
  routes; the composer posts through S02's ingress.
- Case link (FR-12): navigate from the simulated conversation to its case in
  the copilot workbench, so the owner can role-play the employee side (US5).
- SMS only here; the email switcher is S18. The page exposes the control slots
  that S04 (presets/reset) and S05 (link identity) fill in.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest route/component tests: composer submit → BFF ingress
  call; thread renders read-back replies; role gating enforced (unauthenticated
  / wrong-role access rejected).
- **② E2E (browser):** open the Simulator from the nav (this slice CREATES the
  entry), send a message as a simulated customer, see the agent's reply appear
  in the thread; click the case link and land on the copilot case; screenshots.
- **③ Product (PAC):** PAC-2 core path — owner states a preference and sees it
  honored in a later simulated conversation (full sign-off at S33).

## Out of scope

- Identity presets + reset / new-conversation — **S04**.
- Link-identity control — **S05**; email channel switcher — **S18**.
