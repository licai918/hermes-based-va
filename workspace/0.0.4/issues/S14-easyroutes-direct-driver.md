# S14 — EasyRoutes direct driver (read-only delivery status)

- **Milestone:** 0.0.4 — land all seven
- **Track:** T4 Real integrations
- **Size:** M
- **Depends on:** none (parallel to S12)
- **Delivers:** FR-20, FR-21 (EasyRoutes half), NFR-6, NFR-8
- **Surface:** new `drivers/easyroutes/` + driver-selector overlay; no UI

## Goal

FR-20 (grilled decision 17): `toee_easyroutes_read` served by a real REST
client against the EasyRoutes API — delivery status, ETA window, tracking
link — aligned to the existing mock contract, so "when do my tires arrive"
is answered from real data.

## Approach

- REST client with m2m auth: `EASYROUTES_API_TOKEN` + `EASYROUTES_CLIENT_ID`
  env vars (values live only in `.env`/deployment env — **never committed**;
  owner rotates the token that transited chat before cutover).
- Wire as a per-tool overlay beside the Composio driver — the selector
  already routes per-tool; no new driver axis.
- Driver-side deadline → governed `found=false` (knowledge-driver pattern,
  NFR-8); API failure fails closed (FR-21), never falls back to mock in prod.
- Contract parity: map to the mock's result shape; keep the mock for
  tests/dev (`INTEGRATION_DRIVER=mock` path unchanged).

## Acceptance — three-layer gate

- **① Technical:** client unit tests (recorded fixtures), deadline +
  fail-closed tests, secret-scan gate; smoke against the live API.
- **② E2E (browser):** simulator delivery question answered with real
  status/ETA; screenshot cross-checked against EasyRoutes.
- **③ Product (PAC):** PAC-6 delivery leg.

## Out of scope

- Writes (reschedule/address change) — PRD §6. Route/driver internals beyond
  the customer-facing status fields.
