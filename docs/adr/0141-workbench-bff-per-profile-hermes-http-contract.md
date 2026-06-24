# Workbench BFF reaches per-profile Hermes over HTTP via deterministic tool-dispatch plus the agent API Server

> **Amended by [ADR-0142](0142-local-first-datastore-and-per-profile-api-servers-cloud-deferred.md).**
> The two per-profile backends below are built and run as **local processes**
> (one `HERMES_HOME` + bearer each, reached at `http://localhost:<port>`) and proven
> end-to-end locally first; "separate Cloud Run services" is the deferred target for
> a later cloud-deploy slice.

## Context

ADR-0139 set the direction — `apps/workbench` (Next.js) never imports Hermes and
reaches the `internal_copilot` and `supervisor_admin` profiles over HTTP — but
said only that this is "the per-profile API Server (OpenAI-compatible HTTP, bearer
auth)." It did not define the BFF↔backend contract. ADR-0094 still says BFF
handlers "call `packages/domain-adapters`" in-process (TypeScript), which ADR-0139
invalidated: there is no TS in-process Hermes SDK, and Tool Gate plus the tool
handlers are the Python `toee_hermes` plugin. Today the BFF serves all 32 resource
routes from four in-process TypeScript in-memory stores and a TS mock
`ToolDriver`; no per-profile API Server exists and nothing calls Python over HTTP.

Two facts make a single "call the OpenAI-compatible API Server" answer
insufficient:

- **Most BFF routes are deterministic CRUD**, not agent turns: list/get/claim/
  assign/resolve a case, read audit, read/save/submit knowledge slots, list eval
  runs, manage accounts. Driving these through a chat endpoint — letting the LLM
  decide to call `list_cases` and parsing the result out of a completion — is
  non-deterministic, slow, and wrong for a queue/table UI.
- **The data those routes touch is the Toee Business Datastore** (ADR-0140:
  Postgres system-of-record for cases, threads, audit, accounts, knowledge
  versions, eval runs), reached through governed `toee_*` plugin tools — not
  through Hermes native memory and not through a chat completion.

Only a few routes are genuine agent turns: `POST /api/copilot/chat` and the
`POST /api/copilot/drafts/*` generations.

## Decision

Define the per-profile Hermes HTTP surface as **two capabilities behind one
per-profile deployment**, both bearer-authenticated, both running under that
profile's `HERMES_HOME` (ADR-0139) so the Profile Tool Allowlist and Tool Gate
apply identically no matter which path entered:

1. **Deterministic tool-dispatch API — serves the resource routes.**
   `POST /v1/tools:dispatch` with body `{ "tool", "action", "params" }` runs the
   Python `toee_hermes` `execute_tool(...)` directly — no LLM — under the request
   profile, and returns the handler's JSON. Tool Gate denials and backend failures
   return as governed `{ "error": ... }` JSON with HTTP 200 (ADR-0020/0033: no
   fabrication, handlers never raise); only transport/auth/shape problems use 4xx.
   This is the same `execute_tool` + ADR-0070 v1 catalog the external pipeline
   uses, so business rules and Tool Gate are not reimplemented (preserves the
   ADR-0096 "no profile/tool drift" intent).

2. **Agent-turn API — serves chat + drafts.** Genuine generations
   (`/api/copilot/chat`, `/api/copilot/drafts/*`) use the Hermes OpenAI-compatible
   API Server / embedded `AIAgent` run under the same profile.

**BFF mapping (reconciles ADR-0094).** BFF handlers keep their resource-oriented
routes and the route-derived `activeProfile` (ADR-0092/0093); the browser still
never sees raw `{ tool, action }` envelopes. Internally each handler calls the
per-profile HTTP API instead of an in-process TS executor: resource routes →
`tools:dispatch`; chat/drafts → agent-turn. The BFF picks the backend by profile —
`/api/copilot/*` → the `internal_copilot` base URL + token, `/api/admin/*` → the
`supervisor_admin` base URL + token. ADR-0094 is amended: "call
`packages/domain-adapters`" becomes "call the per-profile Hermes HTTP API";
`packages/domain-adapters` survives only as the shared TypeScript request/response
**types** for that API (the ADR-0070 action catalog), not as an in-process
executor.

**Auth + config.** The BFF holds one bearer token per profile and resolves base
URLs from environment, e.g. `HERMES_COPILOT_API_URL` / `HERMES_COPILOT_API_TOKEN`
and `HERMES_ADMIN_API_URL` / `HERMES_ADMIN_API_TOKEN`. The backend validates the
bearer with a constant-time compare and runs every dispatch under its fixed
profile home; tokens never reach the browser. This mirrors the gateway's existing
`X-Internal-Job-Secret` shared-secret pattern (ADR-0106), one token per profile.

**Datastore + deployment.** Tool handlers read/write the Toee Business Datastore
(ADR-0140), activated on demand (ADR-0025). The two employee profiles deploy as
separate Cloud Run services (one `HERMES_HOME` each, matching ADR-0139's separate
homes), alongside the existing external Channel Gateway and the workbench. Until
Postgres lands, dispatch runs against the existing `MockDriver`, so the HTTP seam
is built and contract-tested before the database exists.

## Considered options

- **Two capabilities (tool-dispatch + agent-turn) behind one per-profile home
  (chosen).** Deterministic reads/writes stay deterministic; genuine agent turns
  use the agent; one plugin, one Tool Gate, one allowlist per profile; honors
  ADR-0139/0140 and keeps ADR-0094's browser contract.
- **Everything through the OpenAI-compatible chat endpoint (rejected).**
  Non-deterministic CRUD, wasted tokens and latency, brittle parsing; cannot back
  a queue/table UI reliably.
- **A standalone Toee REST service separate from Hermes (rejected for v1).** Would
  duplicate Tool Gate/allowlist or bypass them, reintroducing the profile/tool
  drift ADR-0096/0139 avoid. Reusing `execute_tool` under the profile home keeps
  one governance path.
- **Resource-shaped REST on the backend (`GET /v1/cases`, …) instead of a tool
  envelope (rejected for v1).** More backend surface to design and version per
  resource; `tools:dispatch` maps 1:1 onto the existing registry + ADR-0070
  catalog, so the BFF — already organized around tool actions — translates its
  resource routes with the least new contract. Browser-facing routes stay
  resource-oriented regardless (ADR-0094).
- **Keep ADR-0094's in-process TS executor (rejected).** ADR-0139 established
  there is no TS in-process Hermes SDK; the tool handlers are Python.

## Verification

This ADR is design-only. The accompanying tracer-bullet slice proves the contract
end to end for one resource (`GET /api/copilot/cases`):

- Python: a FastAPI tool-dispatch app exposing `POST /v1/tools:dispatch` +
  `GET /healthz`, with tests asserting bearer enforcement (401), governed-JSON
  passthrough for an allowlisted action, and profile-allowlist denial returned as
  governed `{ "error": ... }`.
- TypeScript: a `HermesApiClient` whose contract tests assert the request shape
  (URL, `POST`, `Authorization: Bearer`, `{ tool, action, params }` body) and
  response parsing/error handling against a fake `fetch`, plus an env-gated wire
  into the cases route that falls back to the in-memory store when no API URL is
  configured.

Follow-ups (not in the tracer): the Postgres datastore (ADR-0140); the agent-turn
path for chat/drafts; per-profile Cloud Run services in the deploy runbook; and
migrating the remaining resource routes off the in-memory stores.
