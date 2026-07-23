# Integrations ops surface: status page, OAuth reconnect, and fail-closed outage semantics

> **Status: Accepted** (decided during 0.0.4, 2026-07-23). The ADR-0133
> ("ops-side Composio connected-account onboarding") follow-up, deferred there
> and delivered across the T5 track on `feat/0.0.4-land-all`: **S15** (FR-23)
> the `/admin/integrations` status page + governed admin read, **S16** (FR-24)
> the scheduled health probes, **S17** (FR-25, this ADR) the in-app reconnect
> flows + the OAuth callback design. It also records the T4 pieces this surface
> makes observable: the EasyRoutes direct driver (FR-20) and the fail-closed
> outage semantics of the whole T4/T5 track (FR-21).

## Context

ADR-0133/0136 left integration health as *lazy discovery*: an expired or
missing credential surfaced only when a customer's turn failed. There was no
status page, no probe cadence, and no way to reconnect a broken connection
without a vendor-console hunt. ADR-0133 explicitly deferred the ops surface.

T4 made three Layer-1 tools reach live backends (Composio Shopify/QBO/Square)
and added a direct EasyRoutes REST driver, so "is this connection actually
configured and reachable?" became a real, answerable question worth surfacing
before a customer feels the gap. T5 is that surface.

Two properties are non-negotiable — they are the track's spine:

1. **Honesty.** A health surface must never paint an owner-blocked or expired
   connection green. `not_configured ≠ failed ≠ ok`, never conflated; no
   fabricated timestamp or "healthy".
2. **No secret ever leaves.** Only booleans, version-pin strings, env-var
   *names*, and probe reason strings — never a token/key/account-id value. The
   CI secret-scan gate stays green (NFR-6).

## Decision

### 1. Ops surface (S15, FR-23) — a governed admin read, admin-only

`/admin/integrations` lists seven rows (Composio Shopify/QBO/Square, EasyRoutes,
SimpleTexting, OpenRouter, and the Gadget mapping endpoint). It is served by a
new governed tool `toee_integrations.get_integrations_status`, registered
end-to-end (catalog + plugin manifest/schemas + `supervisor_admin` allowlist +
`_AGENT_EXCLUDED_ACTIONS`), and dispatched by the admin BFF over the Supervisor
Admin Profile API (the workbench stays API-only, ADR-0156).

`configured` reuses each driver's OWN env-presence signal read against the
serving process's environment (the same docker-compose `env_file` the
tool-executing processes share), so green means a call would actually run. The
page is deliberately **admin-only** (`lib/auth/access.ts`
`isAdminOnlyPath`), narrower than the supervisor+admin dead-letter operations
view: integrations are a *credential* surface (gap-review P4).

### 2. Scheduled health probes (S16, FR-24) — a typed job on the T2 queue

`integration_probe` is a recurring job type on the same `(type, window)`
dedupe tick retention uses (ADR-0155 §4), run by the background worker at a
15-min cadence. One cheap **authenticated** read per integration
(connected-account status for Composio, a bounded sentinel for
EasyRoutes/Gadget, an authenticated `GET /account` for SimpleTexting, `GET /key`
for OpenRouter). Each records exactly one of the three honest states per cycle;
a `failed` probe emits an alert-greppable ERROR log line. Results land in
`integration_probe` (migration 0015) and the page reads the latest row per
integration as its badge.

**A false `ok` is the one thing forbidden.** Every ambiguous/empty read raises
→ recorded `failed`. OpenRouter deliberately probes `GET /key` (not `/models`,
which is unauthenticated and would paint a dead key healthy).

### 3. In-app reconnect (S17, FR-25) — TWO shapes

Recovery is attributed (the acting admin from session context, ADR-0148 — never
a request param) and written to the Workbench Audit Log. Two governed admin
actions are added to `toee_integrations`, both agent-excluded:

**(a) Composio-managed connections (Shopify/QBO/Square) — OAuth reconnect.**
`initiate_reconnect` generates a connected-account re-auth link via the Composio
SDK. The browser is redirected to the provider, re-grants, and the provider
returns to the workbench callback route, which verifies a session-bound `state`
and lands back on `/admin/integrations`; the page then re-probes that row. The
acting admin is recorded (`integration_reconnect_initiated`). **No token is ever
handled in the workbench — Composio holds the credentials; we hand the admin a
link and get one back.**

**(b) Static-token integrations (EasyRoutes/SimpleTexting/OpenRouter/Gadget) —
guided instructions + re-probe, NOT self-service token replacement** (gap-review
fix P3, binding). There is no OAuth, and the workbench cannot edit deployment
env vars. The panel names the env var and where it lives; the operator rotates
it in the deployment env, then clicks "Re-probe now" (`reprobe_now`, which
reuses the S16 single-integration probe and records + audits the result,
`integration_reprobed`). **No token value is ever displayed, entered, or stored
outside the deployment env.**

`reprobe_now` serves both shapes' completion so a reconnected connection's badge
refreshes immediately rather than on the next 15-min cycle.

### 4. OAuth callback design + its security posture

The callback route (`GET /api/admin/integrations/callback`) is a **new,
externally-reachable route**, so its input is treated as untrusted. Its security
rests on a single bound `state`:

- **State binding.** On `initiate_reconnect`, the workbench route mints a random
  `state`, sets it as an **httpOnly, sameSite=lax** cookie scoped to
  `/api/admin/integrations`, and appends it to the `callback_url` it builds from
  its OWN origin (never client-supplied). The provider round-trips the state.
- **Verify + redirect, nothing else.** The callback compares the query `state`
  to the cookie and does nothing but verify + redirect. It handles no token and
  acts on no other callback parameter. `sameSite=lax` (not strict) so the cookie
  survives the top-level GET redirect back from the provider; `httpOnly` so page
  JS cannot read or forge it. The one-time cookie is always cleared on return.
- **Fail closed.** A missing cookie, a missing query value, or any mismatch is
  **refused** — the page is redirected with `?reconnect=state_mismatch` and
  never signals success. The route is also admin-only (it sits under
  `/api/admin/integrations`), so a caller without a valid admin session is
  401/403'd before the state check runs.

A reconnect that cannot complete (Composio SDK error, owner-blocked creds,
callback state mismatch) surfaces a governed error and never a false
"reconnected".

### 5. Fail-closed outage semantics of the whole T4/T5 track (FR-21)

Every external backend fails closed per tool: a live failure yields a governed
*unavailable* result, never a silent fallback to mock in production. The
EasyRoutes direct driver (FR-20, read-only delivery status: status, ETA window,
tracking link) is wired as a per-tool overlay beside the Composio driver, with a
driver-side deadline → governed `found=false` (NFR-8). The probes, the status
read, and the reconnect actions all inherit this posture: a fault is recorded or
surfaced honestly, never fabricated away.

### 6. Composio version pins (required, boot)

Composio toolkits are pinned to exact versions (a missing/`latest` pin fails
closed at boot, ADR — S12): shopify `20260506_00`, quickbooks `20260623_00`,
square `20260616_00`. `configured` on the status page requires a real
(non-`latest`) pin, so green mirrors exactly what a live call needs.

## Consequences

- An expired or misconfigured integration is now visible on a cadence and
  recoverable from the workbench, attributed and audited — no vendor-console
  hunt, no waiting for a customer turn to fail.
- The workbench never touches a secret: OAuth credentials stay with Composio;
  static tokens stay in the deployment env. The secret-scan gate stays green.
- The OAuth callback is the only new externally-reachable route; its state
  binding is the CSRF defense and is unit-tested for the fail-closed refusal.

### UNVERIFIED — pending the owner's live Composio

The Composio re-auth link generation (`initiate_composio_reconnect` →
`_reauth_redirect_url`) is owner-blocked like the rest of T4: the exact SDK
re-auth surface is a best guess against the 0.15.0 SDK, isolated to one
clearly-marked spot that **fails closed on a wrong guess** (any mismatch raises
→ governed `composio_api_error`, no fabricated link, no audit row). It must be
confirmed against a live connected account at cutover — exactly like the
`_ComposioSdkClient` execute path and the S16 `probe_composio_toolkit` read. The
state-binding, callback verification, audit attribution, role gating, and the
static-token re-probe path are all fully built and tested independent of the
live SDK.

## Considered options

- **Store the OAuth state in a DB table** rather than an httpOnly cookie —
  rejected as unnecessary storage: the standard OAuth state-cookie pattern binds
  to the same browser + admin session with no new table, and the cookie is
  httpOnly + sameSite so it cannot be read or forged. (Ceiling noted in code:
  HMAC the state with the session accountId if multiple admins ever share one
  browser and that becomes a concern.)
- **Self-service token replacement for the static-token integrations** —
  rejected (gap-review P3): the workbench cannot edit deployment env vars, and a
  token field would put a secret through the workbench. Instructions + re-probe
  keeps every secret in the env.
- **A dedicated `reprobe` per integration vs reusing the scheduled job** — reuse
  the S16 single-integration probe wiring so a manual re-probe can never report
  a state the scheduled one wouldn't.

## Verification

- `hermes-runtime`: `test_integrations_reconnect.py` (attribution fail-closed,
  static-token rejection, fail-closed-no-audit, success audits the admin,
  re-probe records the honest state + audits) + `test_integrations_status.py` +
  `test_integration_probe.py`.
- `hermes`: catalog/manifest/profile/exclusion + admin-stub coverage green with
  the two new actions.
- `apps/workbench`: `reconnect-state.test.ts` (fail-closed state comparison),
  `integrations.test.ts` (reconnect/re-probe BFF: non-Composio rejected,
  fail-closed 502 on no link, receipt mapping), `access.test.ts` (reconnect +
  callback subpaths admin-only); `tsc --noEmit` clean.
- `node scripts/secret-scan.mjs --selfcheck && node scripts/secret-scan.mjs`
  clean.
- Launch Eval replay gate stays 26/26.
