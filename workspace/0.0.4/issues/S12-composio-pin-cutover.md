# S12 — Composio SDK pin + production cutover of the 3 Layer-1 tools

- **Milestone:** 0.0.4 — land all seven
- **Track:** T4 Real integrations
- **Size:** M
- **Depends on:** none (parallel to T1/T2 slices)
- **Delivers:** FR-18, FR-21 (Composio half), NFR-6, NFR-8
- **Surface:** `hermes/toee_hermes/drivers/composio/` + env/deploy config; no UI

## Goal

FR-18: the 3 real tools (`toee_shopify_read`, `toee_qbo_read`,
`toee_square_payment_link`) go from staging-smoke to production: SDK surface
pinned against live toolkit versions, prod credentials env-injected,
`INTEGRATION_DRIVER=composio` in the owner's live deployment.

## Approach

- Close the `ponytail:` at `drivers/composio/driver.py:585`: pin and verify
  the SDK call surface against the live toolkits; uncomment/set the
  QuickBooks toolkit-version pin beside the existing Shopify pin.
- Smoke suite per tool: happy path + fail-closed path (backend down →
  governed unavailable result within the driver deadline, NFR-8; never mock
  in prod).
- **Cutover applies to every process that executes tools (gap-review fix
  T4): the gateway AND both dispatch servers (the copilot draft turn calls
  external reads too) — deployment checklist in the PR.**
- Delete the `rest` driver shell (`KNOWN_DRIVERS` entry + the
  `NotImplementedError` arm in `plugin/__init__.py`) — FR-21.
- Credentials env-only; **this slice owns the repo-wide CI secret-scan gate
  (NFR-6, gap-review fix Q3) — one CI job; S14 references it, doesn't
  re-implement.**
- **PAC-6 test-data precondition (gap-review fix P2): create a dedicated
  test customer in the live Shopify store (plus a test order/invoice and an
  EasyRoutes delivery once S14 lands) and wire its phone number into the
  simulator's verified-customer preset — owner PAC runs against test-entity
  data, not a real customer's.**

## Acceptance — three-layer gate

- **① Technical:** smoke suite green against live backends (run from the
  deployment env); fail-closed tests; secret-scan gate in CI.
- **② E2E (browser):** simulator turn answering an order question from live
  Shopify data; screenshot.
- **③ Product (PAC):** feeds PAC-6 (full drill at S24).

## Out of scope

- `get_ar_summary` — **S13**. EasyRoutes — **S14**. Ops page — **S15–S17**.
