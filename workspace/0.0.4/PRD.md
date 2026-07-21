# PRD 0.0.4 — Durable substrate: API-only workbench, Postgres job queue, TS cleanup

- **Status:** drafted from the grilled scope ([EXPLORATION.md](EXPLORATION.md)
  §"GRILLED SCOPE", 11 locked decisions, 2026-07-21).
- **Architecture frame:** [docs/architecture/memory-layers.md](../../docs/architecture/memory-layers.md).
  Governance invariants of ADR-0148 hold everywhere.
- **Prior iterations:** 0.0.1 shipped L4 Customer Memory; 0.0.2 hardened its
  governance; 0.0.3 landed L5 knowledge, the simulator, propose→confirm, L6.
  This iteration makes the substrate **durable and honest**: one
  system-of-record, one queue that survives crashes, one implementation
  language per layer.
- **Precondition (grilled decision 11):** implementation starts only after
  0.0.3 (`feat/0.0.3-land-all`) merges to main. Until then this workspace is
  docs-only.

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

Two ADRs ship with the build: the queue ADR (supersedes ADR-0105's Cloud
Tasks target) and the API-only workbench ADR (supersedes the Slice-2
dual-path architecture).

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

## 6. Out of scope
- Cloud Tasks or any cloud queue service (superseded by the queue ADR).
- Workbench-owned Postgres (rejected Option B — single system-of-record).
- Bulk dead-letter replay, queue metrics dashboards, priority lanes.
- Changing L6 / retention / ingest **behavior** — only their execution
  substrate moves (FR-11).
- The Python keyless chat stub in `copilot_turn.py`.
- Voice, email-provider go-live, Composio cutover, `/admin/integrations`
  (remain 0.0.5+ candidates in the exploration backlog).
- Any 0.0.3 S32/S33 work (owner gates; separate track).

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
