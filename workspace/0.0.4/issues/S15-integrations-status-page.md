# S15 — `/admin/integrations` status page

- **Milestone:** 0.0.4 — land all seven
- **Track:** T5 Integrations ops surface
- **Size:** M
- **Depends on:** S12, S14 (drivers exist to report on), S09 (API-only BFF pattern)
- **Delivers:** FR-23
- **Surface:** workbench admin route + governed admin read endpoint

## Goal

FR-23: an admin-only page showing, per integration (Composio
Shopify/QBO/Square toolkits + EasyRoutes), connection status, pinned
version, last successful call, and last probe result — health visible
before a customer feels it.

## Approach

- Governed admin read (dispatch path, supervisor_admin profile) aggregating:
  Composio connected-account status via the SDK, EasyRoutes token check,
  last-successful-call timestamps (recorded by the drivers), last probe
  row (S16 fills this; renders "never probed" until then).
- Workbench page under the admin route group (ADR-0093 gating), API-only
  (T1 pattern).

## Acceptance — three-layer gate

- **① Technical:** handler + BFF tests; status aggregation unit tests.
- **② E2E (browser):** page shows all four connections with real status;
  screenshot.
- **③ Product (PAC):** feeds PAC-7.

## Out of scope

- Probes — **S16**. Reconnect — **S17**.
