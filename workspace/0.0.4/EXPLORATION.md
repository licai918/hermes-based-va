# 0.0.4 — Exploration (NOT a PRD)

- **Status:** exploration only — grilling in progress. Nothing here is committed
  scope; each candidate graduates to `workspace/0.0.4/PRD.md` only after the
  grilling locks it.
- **Builds on:** 0.0.3 (knowledge L5 + simulator + propose→confirm + L6,
  branch `feat/0.0.3-land-all`; S01–S31 landed, S32/S33 owner gates pending).
- **Date opened:** 2026-07-21 (grilling session)
- **Origin:** 5-agent parallel architecture scan (2026-07-21) — candidates are
  the three zero-conflict directions picked by the owner from that scan.

---

## How to read this

Same convention as 0.0.3's exploration: each candidate is sized (XS/S/M/L) and
carries **options with trade-offs**, not a decision. When a candidate is chosen,
it graduates into `workspace/0.0.4/PRD.md`.

### GRILLED SCOPE — 0.0.4 commits to ALL THREE (2026-07-21 grilling session)

Three grilling rounds, eleven locked decisions:

1. **C1 = API-only workbench.** Delete the in-memory fallback stores
   (`account-store`, gateway `store`, `knowledge-store`, `eval-store`) and the
   TS mock execution path; every BFF route goes through the per-profile Hermes
   dispatch/agent APIs, always. Single system-of-record honored.
2. **One-command local orchestration.** 0.0.4 ships a single dev-up command
   (docker-compose Postgres + both dispatch servers + gateway + workbench) so
   the API-only topology doesn't degrade local dev.
3. **Keyless chat stubs die.** Local real chat requires `OPENROUTER_API_KEY`;
   automated tests use the dispatch server's existing `scripted_completions`
   seam. The TS deterministic chat stub is deleted with the fallback; the
   Python-side keyless stub in `copilot_turn.py` stays as-is (it lives behind
   the API and is today's behavior).
4. **C2 substrate = Postgres job queue** (jobs table + `FOR UPDATE SKIP
   LOCKED`). An ADR superseding ADR-0105's Cloud Tasks target ships with the
   build.
5. **C2 = full suite**: retry with backoff, dead-letter state, and workers as
   separate processes — not just persist-and-recover.
6. **All background work rides the queue**: inbound turn jobs AND the L6
   learning-loop fork, retention sweep, knowledge re-ingest.
7. **Dead-letter gets a workbench view + replay** (supervisor/admin surface,
   replay attributed + audited).
8. **Replay safety = outbound idempotency keys.** Every turn job's outbound
   send carries a deterministic idempotency key checked against an outbound
   record before the Textline POST — any replay is safe; already-sent messages
   are skipped, never re-sent.
9. **Workers split by job type**: a turn worker (latency-sensitive) and a
   background worker (L6/retention/ingest), so a long ingest never queues
   behind or blocks a customer turn.
10. **C3 follows C1**: delete `services/hermes-gateway`,
    `packages/hermes-runtime`, `packages/domain-adapters`,
    `packages/eval-runner` (TS). TS side keeps only `apps/workbench` +
    `packages/shared`; shared constants workbench still needs (e.g.
    `MEMORY_PREFERENCE_SLOTS`) move to `packages/shared` first.
11. **Sequencing: 0.0.4 code starts only after 0.0.3 merges to main**
    (S32/S33 sign-off). Until then, 0.0.4 work is docs-only (this exploration,
    PRD, issues) — zero code-conflict risk with any S32 tuning.

## Candidate index

1. Workbench persistence — retire the in-memory fallback stores — *hardening* (M)
2. Durable job queue — async turns survive process death — *reliability* (M)
3. TS dead-scaffold removal — delete the superseded TypeScript stack — *hygiene* (S)

**Coupling discovered during scan:** Candidate 3 depends on Candidate 1's
direction. `apps/workbench/lib/bff/copilot/*` imports `executeTool` and the
mock driver from `@toee/domain-adapters` — the TS mock driver IS the workbench
in-memory fallback path. Deleting the TS package requires first deciding the
fallback's fate.

---

## Candidate 1 — Workbench persistence (the "STUB SEAM" payoff) — M

**Today:** every workbench BFF route has two paths: a per-profile Hermes API
path (Postgres-backed via hermes-runtime datastore; active when
`HERMES_*_API_URL/TOKEN` set — `.env.local` sets them) and an in-memory
fallback (`lib/auth/account-store.ts`, `lib/gateway/store.ts`,
`knowledge-store.ts`, `eval-store.ts`) that loses accounts/lockouts/claims on
restart.

**The real question is NOT "write Postgres code" — the Postgres twins already
exist behind the admin/copilot APIs.** The question is what the fallback should
become:

- **Option A — delete the fallback, API-only.** Workbench always requires the
  two dispatch servers (8081/8082). Aligns with CONTEXT.md single
  system-of-record; makes local dev = prod topology; unlocks Candidate 3 fully.
  Cost: local dev and vitest suites need a story (mock at the HTTP client seam
  instead of the store seam?).
- **Option B — replace fallback with workbench-owned Postgres.** Second
  system-of-record for cases/accounts — conflicts with CONTEXT.md ("Toee
  Business Datastore" is THE record). Likely rejected; listed for honesty.
- **Option C — keep fallback, persist only what has no API twin.** Audit which
  of the 4 stores still lack a real API/datastore path (accounts lockout state?
  eval reports?) and close only those gaps.

**Open questions:** owner intent (prod robustness vs local-dev persistence?);
what breaks in vitest if the store seam goes away; whether eval-store's real
fix is Candidate-1 work or the eval-report ingestion from `eval/reports/*.json`.

## Candidate 2 — Durable job queue — M

**Today:** `LocalDispatchingJobQueue` (in-process daemon thread,
`hermes-runtime/hermes_runtime/job_dispatch.py`) is wired even in the
production composition root (`gateway_composition.py:157`). Process death loses
queued async turns. ADR-0105 names Cloud Tasks as the production target;
ADR-0142 says local-first — the two are in tension.

- **Option A — Postgres-backed queue** (jobs table + `FOR UPDATE SKIP LOCKED`
  worker loop). Local-first compatible, no new infra, same DB ops story.
  Dedupe/idempotency keys already exist in the gateway store.
- **Option B — Cloud Tasks.** Matches ADR-0105 letter, but requires GCP in
  every environment or a second local path — contradicts ADR-0142 posture today.
- **Option C — accept the loss window.** Textline retries + inbound dedupe may
  already bound the damage; measure before building.

**Open questions:** what actually happens today when the process dies mid-turn
(does Textline redeliver? does dedupe swallow the retry?); worker in-process vs
separate process; retry/dead-letter semantics; does ADR-0105 need superseding.

## Candidate 3 — TS dead-scaffold removal — S

**Zero-reference (delete-safe today):**
- `services/hermes-gateway` — Fastify server never built ("lands in issue #17");
  Python `gateway_app.py` superseded it.
- `packages/hermes-runtime` — stub ("lands in slice #13", voided by ADR-0139);
  referenced only in `apps/workbench/package.json` dependencies, zero code
  imports. Drop the dep line + delete.

**Blocked on Candidate 1:**
- `packages/domain-adapters` — genuinely imported by workbench BFF
  (`executeTool`, mock driver, `MEMORY_PREFERENCE_SLOTS`) and by
  `packages/eval-runner`. Deletable only under Candidate 1 Option A; under
  Option C it stays and merely stops growing (already 3 tools behind Python).
- `packages/eval-runner` (TS) — Python `hermes/eval_runner` is the live one;
  confirm the TS twin is unreferenced by CI before deleting.

**Open questions:** is `MEMORY_PREFERENCE_SLOTS` (a shared constant, not mock
behaviour) better moved to `packages/shared` regardless of the rest; does any
CI job build/test the TS packages today.

---

## Grilling log

- 2026-07-21 — session opened; coupling C3→C1 established from code
  (`apps/workbench/lib/bff/copilot/chat.ts:9` et al.). Round 1 questions posed
  to owner: C1 direction (A/B/C), C2 queue substrate, C2 delivery boundary,
  C3 aggressiveness.
- 2026-07-21 — **Round 1 LOCKED (owner):**
  1. **C1 = Option A** — delete the in-memory fallback; workbench is API-only
     (always requires the per-profile dispatch servers).
  2. **C2 substrate = Postgres queue** (jobs table + `FOR UPDATE SKIP LOCKED`);
     needs an ADR superseding ADR-0105's Cloud Tasks target.
  3. **C2 boundary = full suite** — retry + dead-letter + worker as a separate
     process (docker-compose service), not just persist-and-recover.
  4. **C3 = follows C1-A** — delete `services/hermes-gateway`,
     `packages/hermes-runtime`, `packages/domain-adapters`,
     `packages/eval-runner` (TS); TS side keeps only `apps/workbench` +
     `packages/shared`.
- Round 2 (consequences) posed: local dev topology, keyless chat story,
  queue job scope, dead-letter visibility.
- 2026-07-21 — **Round 2 LOCKED (owner):** one-command orchestration; local
  chat requires a key (stubs deleted TS-side, `scripted_completions` for
  tests); ALL background work (turn + L6 + retention + ingest) rides the
  queue; dead-letter gets a workbench view + replay.
- 2026-07-21 — **Round 3 LOCKED (owner):** 0.0.4 code waits for 0.0.3 →
  main merge (docs-only until then); replay safety via outbound idempotency
  keys (send-record check before every Textline POST); workers split by job
  type (turn worker vs background worker).
- 2026-07-21 — grilling closed; scope graduated to [PRD.md](PRD.md).
  PRD-level defaults (not grilled, overridable at review): retry = 3 attempts
  exponential backoff; replay permission = supervisor/admin, audited;
  orchestration = docker-compose extension + one dev script; branch =
  `feat/0.0.4-durable-substrate` off main post-merge.
