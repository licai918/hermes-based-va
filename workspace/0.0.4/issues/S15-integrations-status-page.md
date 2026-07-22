# S15 — `/admin/integrations` status page

- **Milestone:** 0.0.4 — land all seven
- **Track:** T5 Integrations ops surface
- **Size:** M
- **Depends on:** S12, S14 (drivers exist to report on), S09 (API-only BFF pattern)
- **Delivers:** FR-23
- **Surface:** workbench admin route + governed admin read endpoint

## Goal

FR-23: an admin-only page showing, per integration (Composio
Shopify/QBO/Square toolkits, EasyRoutes, **SimpleTexting, OpenRouter** — owner
decision, gap-review P1), connection status, pinned version where
applicable, last successful call, and last probe result — health visible
before a customer feels it.

## Approach

- Governed admin read (dispatch path, supervisor_admin profile) aggregating:
  Composio connected-account status via the SDK, EasyRoutes token check,
  **SimpleTexting token check and OpenRouter key check**, last-successful-call
  timestamps (recorded by the drivers/senders), last probe row (S16 fills
  this; renders "never probed" until then).
- **New governed tool registered end-to-end (gap-review fix T3): tool
  catalog + plugin schemas + `supervisor_admin` allowlist + persona param
  conventions — the 0.0.3 S31 lesson (undocumented tool conventions cause
  rework) applies.**
- Workbench page under the admin route group (ADR-0093 gating), API-only
  (T1 pattern). **Role note (gap-review P4, deliberate): integrations are
  admin-only (credential surface); the dead-letter view is supervisor+admin
  (operations surface) — recorded here so the asymmetry reads as intent.**

## Acceptance — three-layer gate

- **① Technical:** handler + BFF tests; status aggregation unit tests.
- **② E2E (browser):** page shows all four connections with real status;
  screenshot.
- **③ Product (PAC):** feeds PAC-7.

## Out of scope

- Probes — **S16**. Reconnect — **S17**.
