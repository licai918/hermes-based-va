# PRD 0.0.4 — Land all seven: durable substrate, real integrations, ops surface, eval & metrics completion

- **Status:** drafted from the grilled scope ([EXPLORATION.md](EXPLORATION.md)
  §"GRILLED SCOPE" + §"GRILLED SCOPE ADDENDUM", 19 locked decisions,
  2026-07-21).
- **Architecture frame:** [docs/architecture/memory-layers.md](../../docs/architecture/memory-layers.md).
  Governance invariants of ADR-0148 hold everywhere.
- **Prior iterations:** 0.0.1 shipped L4 Customer Memory; 0.0.2 hardened its
  governance; 0.0.3 landed L5 knowledge, the simulator, propose→confirm, L6
  (merged to main, PR #56). This iteration is a **land-all of the seven
  post-0.0.3 scan directions**: durable substrate (T1–T3), real external
  integrations (T4), integrations ops surface (T5), eval completion (T6),
  metrics instrumentation (T7) — executed in that order, one UAT gate.
- **Precondition:** satisfied — 0.0.3 merged to main 2026-07-21.

---

## 1. Problem Statement

Three lies in the current substrate. (1) The workbench pretends to have a
fallback: an in-memory store twin that loses accounts, lockouts, and case
claims on every restart, drags a whole TypeScript mock-driver package behind
it, and violates the single system-of-record principle the moment it's used.
(2) The gateway pretends to have a queue: async turns run on an in-process
daemon thread (`LocalDispatchingJobQueue`) even in the production composition
root — a crash mid-turn silently loses the customer's message, and ADR-0105's
named target (Cloud Tasks) contradicts the local-first posture of ADR-0142 and
was never built. (3) The repo pretends to have one implementation: a dead
TypeScript runtime/gateway scaffold (superseded by Python since ADR-0139)
still ships, confuses navigation, and lags the live implementation by three
tools.

And four gaps above it. (4) Integrations aren't real: only 3 tools reach a
live backend, verified at staging-smoke only with unpinned SDK toolkits; QBO
AR summary is fail-closed; EasyRoutes — the tool that answers "when does my
tire arrive" — is a mock, so delivery answers are made up. (5) Integration
health is invisible: no status page, no probes (ADR-0133/0136 deferrals) —
an expired connection is discovered when a customer's turn fails. (6) The
eval gate can't exercise a live turn (`_StubAgentHarness` returns empty), the
LLM judge is unwired (semantic assertions have no enforcement at all), and
the email suite has zero transcripts and isn't in CI. (7) The metrics panel
ships honest placeholders: honored-rate is not computed, two tiles count
proxies for uninstrumented events, and the quality-gates panel shows
hand-copied numbers.

## 2. Solution

Three tracks. **T1 — API-only workbench:** delete the four in-memory stores
and the TS mock execution path; every BFF route reaches the Postgres-backed
datastore through the per-profile dispatch/agent APIs, always; local dev keeps
one-command startup via orchestration. **T2 — durable Postgres job queue:**
a jobs table consumed with `FOR UPDATE SKIP LOCKED` by two worker processes
(turn worker, background worker), with retry + backoff, a dead-letter state
surfaced in a workbench view with governed replay, and outbound idempotency
keys making any replay safe against double-sends. All background work — turn
execution, L6 learning fork, retention sweep, knowledge re-ingest — rides it.
**T3 — TS cleanup:** delete the dead TS scaffold and the mock packages T1
orphans; the TS side ends at `apps/workbench` + `packages/shared`.

Then four tracks above the substrate. **T4 — real integrations:** pin
Composio SDK/toolkit versions and cut the 3 Layer-1 tools over to production;
implement QBO AR summary's real reports path; build a direct EasyRoutes REST
driver (read-only delivery status) so delivery answers are real; delete the
`rest` driver shell. Outage semantics: fail closed per tool — never mock in
prod. **T5 — integrations ops surface:** `/admin/integrations` status page,
scheduled health probes riding the T2 queue (failure = page badge + log
alert), and in-app OAuth reconnect flows (the full ADR-0133 deferred
surface). **T6 — eval completion:** a live agent harness through the real
dispatch path; email-suite transcripts recorded and gated in CI; the LLM
judge wired as an every-PR advisory report (real-model live run; the
deterministic replay gate stays the only required check). **T7 — metrics
instrumentation:** the two uninstrumented event counters, honored-rate from a
scheduled judge job on the queue, and the quality-gates panel reading real
report artifacts.

Four ADRs ship with the build: the queue ADR (supersedes ADR-0105's Cloud
Tasks target), the API-only workbench ADR (supersedes the Slice-2 dual-path
architecture), the integrations ADR (ADR-0133 follow-up: ops surface + OAuth
reconnect + EasyRoutes direct driver + fail-closed outage semantics), and the
live-eval ADR (harness + advisory judge wiring, upholding the never-a-gate
stance until a future promotion ADR).

## 3. User Stories

**Rep / supervisor (workbench)**
1. As a rep, I want my account, lockout state, and case claims to survive a workbench restart, so that a deploy never silently logs me out or unclaims my cases.
2. As a supervisor, I want workbench data to always come from the Toee Business Datastore, so that what I see in the UI is what SQL and the audit trail say — no second store to disagree.

**Customer (external agent)**
3. As a customer whose message arrived while the gateway crashed, I want my turn to run when the service comes back, so that my question is never silently dropped.
4. As a customer, I want a replayed turn to never re-send a message I already received, so that operational recovery is invisible to me.

**Supervisor / admin (queue operations)**
5. As a supervisor, I want a dead-letter view listing jobs that exhausted retries (type, payload summary, error, attempts, timestamps), so that stuck work is visible in the UI, not just SQL.
6. As a supervisor, I want a replay button on a dead-lettered job that is attributed to me and audited, so that recovery is governed like every other write.
7. As an admin, I want the L6 learning fork, retention sweep, and knowledge re-ingest to run through the same queue with the same retry/dead-letter semantics, so that background failures are observable in one place.

**Developer / CI**
8. As a developer, I want one command to bring up the full local stack (Postgres, both dispatch servers, gateway, workers, workbench), so that API-only topology costs me nothing daily.
9. As a developer, I want BFF tests to mock at the HTTP client seam with the dispatch server's `scripted_completions` for chat, so that deleting the store seam doesn't gut test coverage.
10. As a developer, I want the TS workspace to contain only `apps/workbench` and `packages/shared`, so that there is exactly one implementation of every layer to read, test, and extend.
11. As a developer, I want a long-running ingest job to never delay a customer turn, so that queue unification can't regress latency.

**Customer (real integrations — T4)**
12. As a customer, I want delivery answers (status, ETA window, tracking link) to come from the real EasyRoutes system, so that "when do my tires arrive" is answered accurately, not from a mock.
13. As a customer, I want order/invoice/payment-link answers to come from live Shopify/QBO/Square in production, so that what the agent says matches reality.
14. As a customer, I want the agent to say it can't check right now (fail closed) when a backend is down, so that I never get invented data.

**Admin (ops surface — T5)**
15. As an admin, I want an integrations page showing each connection's status (Composio toolkits, EasyRoutes token) and last successful call, so that health is visible before a customer feels it.
16. As an admin, I want scheduled health probes that badge the page and alert the logs on failure, so that an expired connection is caught by the system, not by a failing customer turn.
17. As an admin, I want to reconnect a broken integration from the workbench (OAuth redirect flow, attributed and audited), so that recovery doesn't require a vendor console hunt.

**Developer / owner (eval & metrics — T6/T7)**
18. As a developer, I want the eval harness to run a real turn through the dispatch path, so that the gate proves the pipeline, not just the replay plumbing.
19. As a developer, I want every PR to attach a real-model live-eval + judge advisory report without blocking the merge, so that semantic regressions are visible while CI stays deterministic.
20. As a developer, I want the email suite recorded and replay-gated in CI, so that the email pipeline can't silently regress.
21. As the owner, I want honored-rate, self-service usage, and L6 confirmed-entry counts to be real measured values on the metrics panel, so that decisions rest on data, not placeholders.
22. As the owner, I want the quality-gates panel to show the latest actual recall/judge reports, so that the numbers on screen are never stale hand-copies.

## 4. Functional Requirements

### T1 — API-only workbench (grilled decisions 1–3)
- **FR-1** Delete the four in-memory stores — `lib/auth/account-store.ts`,
  `lib/gateway/store.ts`, `lib/gateway/knowledge-store.ts`,
  `lib/gateway/eval-store.ts` — and `lib/gateway/seed.ts`. Every BFF handler
  keeps only its `...ViaApi` path; the store-or-api branch and
  `hermes-api-config`'s "unset = fallback" semantics go away: missing
  `HERMES_*_API_URL/TOKEN` is now a boot-time failure (fail closed), not a
  silent downgrade.
- **FR-2** Account bootstrap moves server-side: the datastore dev-bootstrap
  seeds the rep/supervisor/admin accounts (dev only, existing
  `test_datastore_dev_bootstrap` seam); the workbench never hashes or seeds
  passwords again. Lockout policy (ADR-0018) is enforced by the datastore
  accounts handler — verify parity (5 attempts / 15 min) before deleting the
  TS enforcement, and port any gap.
- **FR-3** The TS chat/draft fallback (`handleChat` template stub, `executeTool`
  mock path in `chat.ts`, `drafts.ts`, `messages.ts`, `deps.ts`) is deleted;
  the agent-turn API is the only chat path. Local real replies require
  `OPENROUTER_API_KEY`; tests script the dispatch server's
  `scripted_completions` seam. The Python keyless stub in `copilot_turn.py`
  is out of scope (unchanged).
- **FR-4** BFF tests migrate from store-seam DI to HTTP-client-seam mocks
  (`hermes-api-client` / `hermes-agent-client`). Coverage parity: every
  behavior currently asserted against the store seam is either re-asserted at
  the client seam or explicitly retired with the fallback (list in the PR).
- **FR-5** One-command dev orchestration: a single entry (script + extended
  docker-compose) brings up Postgres (+ knowledge DB), both dispatch servers,
  the gateway, both workers (T2), and the workbench dev server, with seeded
  dev accounts. Documented as THE local dev path in the workbench README.
- **FR-6** Shared constants the workbench imports from `@toee/domain-adapters`
  (e.g. `MEMORY_PREFERENCE_SLOTS`, tool result types the BFF references) move
  to `packages/shared` with no behavior change, before T3 deletes the package.

### T2 — Durable Postgres job queue (grilled decisions 4–9)
- **FR-7** A `job` table in the Toee Business Datastore (migration shipped):
  id, type, payload (JSONB), status (`queued | running | succeeded | failed |
  dead`), attempts, max_attempts, run_at, locked_at/locked_by, last_error,
  created_at/updated_at. Dedupe key unique-indexed so re-enqueueing an
  already-processed inbound event is a no-op (existing gateway dedupe
  semantics preserved).
- **FR-8** Queue operations via `FOR UPDATE SKIP LOCKED` claim; retry with
  exponential backoff (default max 3 attempts — PRD default, tunable per job
  type); exhausted jobs move to `dead`, never silently dropped. A crashed
  worker's `running` jobs are reclaimed after a lease timeout.
- **FR-9** Two worker processes (docker-compose services): a **turn worker**
  (inbound turn jobs only) and a **background worker** (L6 learning fork,
  retention sweep, knowledge re-ingest). A slow background job can never
  block or queue ahead of a turn job (grilled decision 9 / story 11).
- **FR-10** The gateway's fast-ack path enqueues to the Postgres queue instead
  of the in-process thread; `LocalDispatchingJobQueue` is deleted after
  cutover. Webhook ack latency budget unchanged (enqueue is one INSERT).
- **FR-11** Background-work migration: the L6 learning fork, retention sweep,
  and knowledge re-ingest are enqueued as typed jobs (their triggers —
  post-turn hook, schedule, admin action — now enqueue instead of executing
  inline). Behavior and audit semantics unchanged; only the execution
  substrate moves. The admin "re-ingest" panel action (0.0.3 FR-6 stub)
  becomes a real enqueue + status readback.
- **FR-12** **Outbound idempotency (grilled decision 8):** an outbound-send
  record keyed by a deterministic idempotency key (derived from job id +
  turn/reply identity) is written around every Textline POST; the sender
  checks it before POSTing. A replayed or retried job whose send already
  happened skips the POST and records the skip. This closes the
  crash-between-send-and-commit double-text window for retries and replays
  alike.
- **FR-13** Dead-letter workbench view (supervisor/admin roles, ADR-0093
  route-gating): list dead jobs with type, payload summary, attempts,
  last_error, timestamps; a **Replay** action re-enqueues (attempts reset,
  original idempotency lineage kept) attributed to the acting account and
  written to the Workbench Audit Log. No bulk replay in v1.
- **FR-14** Queue ADR ships with the build: Postgres queue chosen, ADR-0105's
  Cloud Tasks target formally superseded, local-first (ADR-0142) alignment
  stated, lease/retry/dead-letter semantics recorded.

### T3 — TS dead-scaffold removal (grilled decision 10)
- **FR-15** Delete `services/hermes-gateway` and `packages/hermes-runtime`
  (zero code references; drop the dead dependency line in
  `apps/workbench/package.json`). No behavior change — CI green is the proof.
- **FR-16** After FR-1..6 land: delete `packages/domain-adapters` and
  `packages/eval-runner` (TS). Workspace config (`pnpm-workspace.yaml`,
  `vitest.workspace.ts`, `tsconfig.base.json` paths) updated; the TS side
  ends at `apps/workbench` + `packages/shared`.
- **FR-17** API-only workbench ADR ships with the build: the Slice-2 dual-path
  (store fallback) architecture is formally retired; the HTTP client seam is
  the workbench's only backend seam.

### T4 — Real integrations: Composio cutover + EasyRoutes (grilled decisions 16–17)
- **FR-18** Composio production cutover of the 3 Layer-1 tools
  (`toee_shopify_read`, `toee_qbo_read`, `toee_square_payment_link`): SDK
  surface pinned against live toolkit versions (close the `ponytail:` at
  `drivers/composio/driver.py:585`; QuickBooks pin uncommented alongside the
  existing Shopify pin), prod credentials env-injected,
  `INTEGRATION_DRIVER=composio` in the owner's live deployment, a smoke suite
  covering each tool's happy path + fail-closed path.
- **FR-19** `get_ar_summary` real path: implemented via the QBO reports API
  through Composio; the deliberate `_AR_SUMMARY_UNAVAILABLE` fail-closed is
  retired. Same governed result envelope as the mock contract.
- **FR-20** EasyRoutes direct driver, **read-only delivery status**: a REST
  client (m2m auth via `EASYROUTES_API_TOKEN` / `EASYROUTES_CLIENT_ID`, env
  only — values never committed; owner-supplied credentials rotated after
  transiting chat) serving `toee_easyroutes_read` with delivery status, ETA
  window, and tracking link, aligned to the existing mock contract. Wired as
  a per-tool overlay beside the Composio driver (the driver selector already
  routes per-tool; no new axis). Driver-side deadline → governed
  `found=false`, mirroring the knowledge-driver pattern.
- **FR-21** Outage semantics everywhere in T4: a live backend failure fails
  closed per tool (governed unavailable result) — never a silent fallback to
  mock in production. The `rest` driver shell (`KNOWN_DRIVERS` entry +
  `NotImplementedError` arm) is deleted.
- **FR-22** Integrations ADR ships (with T5's surface): ADR-0133 follow-up
  recording cutover, pins, EasyRoutes direct driver, fail-closed semantics.

### T5 — Integrations ops surface (grilled decision 15)
- **FR-23** `/admin/integrations` page (admin role, ADR-0093 gating): per
  integration — Composio toolkits (Shopify/QBO/Square) and EasyRoutes —
  connection status, pinned version, last successful call, last probe result.
  Served by a governed admin read (workbench stays API-only per T1).
- **FR-24** Scheduled health probes as a typed background job on the T2 queue
  (cheap read per integration); failure surfaces as a page badge + structured
  log alert; probe history retained per the retention classes.
- **FR-25** In-app reconnect: for Composio-managed connections, an OAuth
  redirect flow (connected-account re-auth link generation → provider → callback
  landing back on the page), attributed to the acting admin and audited; for
  EasyRoutes (static m2m token), a guided token-replacement flow (env
  update + probe re-run). Callback design and its security posture recorded
  in the integrations ADR (FR-22).

### T6 — Eval completion (grilled decisions 13–14)
- **FR-26** Live agent harness: `_StubAgentHarness` replaced by a harness
  driving a real turn through the dispatch/gateway path (simulated ingress,
  `REPLY_SENDER=simulated`), with two model modes — `scripted`
  (`scripted_completions`, deterministic) and `live` (real OpenRouter model).
- **FR-27** Email suite lands in CI: transcripts recorded for
  `eval/scenarios/email/14–23` via the harness; `email_go_live` joins the CI
  replay matrix as a required check alongside `text_first_launch`.
- **FR-28** Judge production wiring — advisory forever (until a future
  promotion ADR): every PR runs the live-model harness + judge over the
  scenario set and attaches the advisory report as a CI artifact/comment;
  it never blocks the merge. The deterministic scripted replay gate remains
  the only required eval check. Judge model/config from S27's tuned baseline.
- **FR-29** Live-eval ADR ships: harness architecture, advisory stance
  reaffirmed, every-PR real-model cadence + cost note, flake handling
  (advisory = no retry theater).

### T7 — Metrics instrumentation (grilled decision 18)
- **FR-30** Instrument the two proxy tiles at their event sites:
  `selfServiceUsage` (customer self-service query/delete events) and
  `l6ConfirmedEntries` (L6 confirm events) become real counters; the
  `proxy:true` flags drop off.
- **FR-31** Honored-rate becomes real: a scheduled judge job (typed job on
  the T2 queue, background worker) runs the tuned judge over recent
  transcripts and persists the honored-rate aggregate the metrics handler
  reads; the "non-live placeholder" label drops off.
- **FR-32** `QualityGatesPanel` reads the latest recall/judge report
  artifacts (from FR-28 runs and the knowledge gate harness) instead of
  hand-copied constants; shows report timestamp + provenance.

## 5. Non-Functional Requirements
- **NFR-1** Webhook ack p95 does not regress vs the in-process queue
  (enqueue = single INSERT; measure before/after in the simulator).
- **NFR-2** Turn end-to-end latency: queue claim adds < 500 ms p95 over the
  current thread handoff under normal load (tunable poll interval / LISTEN-
  NOTIFY allowed as the upgrade path; record the choice in the queue ADR).
- **NFR-3** Zero message loss on crash: kill a worker mid-turn in the
  simulator; the job is reclaimed and completes; no duplicate outbound
  (FR-12 evidence).
- **NFR-4** CI runs the full suite against the API-only workbench (dispatch
  servers + Postgres already provisioned in CI since 0.0.3 S30); no test
  depends on the deleted stores.
- **NFR-5** One-command dev-up completes to a usable logged-in workbench.
- **NFR-6** No secret in the repo: EasyRoutes/Composio credentials are env
  vars only; CI secret-scan (grep gate) proves no token string lands in a
  commit.
- **NFR-7** The required CI wall stays deterministic: only scripted-mode
  eval, replay gates, and unit/integration suites are required checks; every
  live-model job is non-blocking (FR-28).
- **NFR-8** T4 tools honor the existing per-tool deadline discipline: a hung
  external backend degrades to the governed unavailable result within the
  driver deadline, never blocks a turn.

## 6. Out of scope
- Cloud Tasks or any cloud queue service (superseded by the queue ADR).
- Workbench-owned Postgres (rejected Option B — single system-of-record).
- Bulk dead-letter replay, queue metrics dashboards, priority lanes.
- Changing L6 / retention / ingest **behavior** — only their execution
  substrate moves (FR-11).
- The Python keyless chat stub in `copilot_turn.py`.
- EasyRoutes **writes** (rescheduling, address changes) — read-only this
  iteration; a write path needs its own governance grilling.
- Judge as a CI gate — explicitly out; requires a future promotion ADR with
  measured precision (grilled decision 13).
- Real email **provider** go-live (sending via a real provider) — the email
  eval suite (FR-27) exercises the simulated pipeline only.
- Voice (still no turn path).

## 7. Acceptance (PAC) — three-layer gate per 0.0.3 convention
Technical CI + browser E2E + owner PAC in the simulator:
- **PAC-1 (T1):** restart the full stack mid-session — rep account, lockout
  state, and case claims survive; workbench boots refusing to start without
  API config (screenshot of fail-closed error).
- **PAC-2 (T2 durability):** send a simulator SMS, kill the turn worker
  before reply, restart — reply arrives exactly once (FR-12 skip visible in
  the outbound record).
- **PAC-3 (T2 dead-letter):** force a job to exhaust retries; it appears in
  the dead-letter view; Replay (as supervisor) re-runs it; audit row shows
  the acting account.
- **PAC-4 (T2 background):** trigger knowledge re-ingest from the admin
  panel; the job runs on the background worker while a simultaneous simulator
  turn completes without added delay.
- **PAC-5 (T3):** the TS packages are gone, CI is green, and
  one-command dev-up yields a working workbench (PAC-1's flow re-run on the
  cleaned tree).
- **PAC-6 (T4):** in the live deployment, the owner asks (as a simulated
  verified customer) an order question, an AR/invoice question, and a
  **delivery question** — answers come from live Shopify/QBO/EasyRoutes data
  (cross-checked against the source systems); with one backend deliberately
  broken, the agent fails closed instead of inventing.
- **PAC-7 (T5):** the integrations page shows all four connections healthy;
  the owner breaks one (revoke/expire), the scheduled probe badges it within
  one probe cycle, and the in-app reconnect flow restores it (audit row shows
  the acting admin).
- **PAC-8 (T6):** a PR shows the required scripted replay gate green
  (including the email suite) plus the non-blocking real-model live-eval +
  judge advisory report attached; the owner reads one report end-to-end.
- **PAC-9 (T7):** the metrics panel shows honored-rate, self-service usage,
  and L6 confirmed entries as real values (placeholder/proxy labels gone);
  QualityGatesPanel shows the latest report with timestamp; owner
  cross-checks one number against its source.
