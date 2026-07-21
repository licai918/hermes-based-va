# S17 — In-app reconnect flows + integrations ADR

- **Milestone:** 0.0.4 — land all seven
- **Track:** T5 Integrations ops surface
- **Size:** M
- **Depends on:** S15
- **Delivers:** FR-25, FR-22
- **Surface:** workbench reconnect UI + OAuth callback route + governed admin action + ADR

## Goal

FR-25 (grilled decision 15): a broken integration is recoverable from the
workbench — Composio connections via an OAuth redirect flow, EasyRoutes via
a guided token-replacement flow — attributed and audited. FR-22: the
integrations ADR (ADR-0133 follow-up) ships here.

## Approach

- Composio: governed admin action generates the connected-account re-auth
  link (Composio SDK), browser redirects to the provider, callback route
  lands back on `/admin/integrations` and re-probes; acting admin recorded
  in the audit log.
- EasyRoutes (static m2m token — no OAuth): guided flow showing where the
  env var lives + a "re-probe now" action; no token value ever displayed or
  stored outside env.
- Callback security: state parameter bound to the admin session; callback
  route does nothing but verify + redirect (no token handling in workbench —
  Composio holds the credentials).
- **Integrations ADR**: ops surface, OAuth callback design + security
  posture, EasyRoutes direct driver, fail-closed outage semantics, pins.

## Acceptance — three-layer gate

- **① Technical:** callback state-verification tests; audit-row tests;
  role-gating tests.
- **② E2E (browser):** full reconnect round-trip on a deliberately expired
  connection; screenshots of each step + the audit row.
- **③ Product (PAC):** PAC-7 reconnect leg.

## Out of scope

- New provider onboarding UI (reconnect of existing connections only).
