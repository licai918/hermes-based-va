# API-only workbench: Slice-2 dual-path architecture retired

> **Status: Accepted — retirement complete** (decided during 0.0.4,
> 2026-07-22). Ships on `feat/0.0.4-land-all`: **S09** (FR-1, FR-3, FR-4,
> NFR-4) deleted the four in-memory stores (`lib/auth/account-store.ts`,
> `lib/gateway/store.ts`, `lib/gateway/knowledge-store.ts`,
> `lib/gateway/eval-store.ts`), the dev seed, and the TS chat/draft stub
> execution path, leaving every BFF handler on only its `...ViaApi` path.
> **S11** (this ADR, FR-16, FR-17) deletes the two packages that path left
> orphaned — `packages/domain-adapters` and the TypeScript
> `packages/eval-runner` — and formally retires the architecture below.

## Context

Slice 2 gave the workbench two parallel ways to answer a BFF request:

1. **The store path** — an in-memory `GatewayStore` (plus sibling
   account/knowledge/eval stores) seeded with mock data, read and written
   directly in the Next.js process.
2. **The API path** — an HTTP call through `HermesApiClient`/
   `HermesAgentClient` to a per-profile Hermes dispatch server.

Every handler branched on which one was configured. This was the right call
*then*: it let the workbench UI, the BFF resource routes, and their tests
exist before any Python dispatch server, database, or agent-turn API did.
`packages/domain-adapters` (mock Domain Adapter Tool drivers + the
`ToolExecutionContext`/`ToolGate` types the store path dispatched through)
and the TypeScript `packages/eval-runner` (a scenario-fixture harness that
ran assertions against the store path's mock drivers) existed to make that
first path self-contained.

0.0.4 removed the reason for a second path to exist:

- ADR-0140/0142 made Postgres the system of record and proved the per-profile
  API servers runnable locally, with no cloud credential required.
- **S09** cut the workbench over to `...ViaApi` only and deleted the store
  path outright — the branch, not just its default, is gone.
- With the store path gone, `packages/domain-adapters` had zero remaining
  code importers (its mock drivers had no caller) except
  `ToolExecutionContext`, whose only remaining consumer was
  `packages/eval-runner/src/harness.ts`. Deleting the package with its one
  consumer needed no extraction to `@toee/shared` — S07 had already moved
  everything the API path itself depends on (`MEMORY_PREFERENCE_SLOTS`, the
  tool/action catalog, etc.) there in advance.
- The Python `hermes/eval_runner` (`hermes-runtime`'s live per-profile
  dispatch servers underneath it) is the eval runner that actually gates CI
  (`.github/workflows/ci.yml`'s `eval-gate` job runs
  `python -m eval_runner --harness replay`); the TypeScript
  `packages/eval-runner` never wired into CI and had no live caller once its
  mock drivers went with the store path.

## Decision

**The HTTP client seam (`HermesApiClient` / `HermesAgentClient` dispatching
to a per-profile Hermes API server) is the workbench's only backend seam.**
There is no in-memory fallback, no mock execution path, and no second set of
TypeScript mock drivers to keep in sync with the real one. A missing
`HERMES_*_API_URL`/`_API_TOKEN` is a boot-time failure, not a silent
downgrade to a mock store (S09).

Concretely, this slice:

- Deletes `packages/domain-adapters` in full (34 files: the mock drivers for
  every v1 Domain Adapter Tool, `ToolGate`/`ToolExecutionContext`,
  `execute-tool.ts`, and their tests).
- Deletes the TypeScript `packages/eval-runner` in full (17 files: fixture
  loading, the standard assertion package, the JSON report builder, and the
  stub agent harness in `harness.ts` — the sole remaining consumer of
  `ToolExecutionContext`, so it goes with the package rather than being
  extracted).
- Drops every line of workspace config that named them: the
  `@toee/domain-adapters` dependency in `apps/workbench/package.json`, both
  packages' `transpilePackages`/Dockerfile `COPY` entries, and the root
  `eval` npm script (`tsx packages/eval-runner/src/cli.ts`) along with the
  now-unused `tsx` devDependency. `pnpm-workspace.yaml` needed no edit — its
  `packages/*` glob does not name packages individually. `tsconfig.base.json`
  carries no per-package path mappings and needed no edit either.
- Regenerates `pnpm-lock.yaml` via `pnpm install`.

**The deletion set this ADR records, across both slices:**

| Slice | Deleted | Reason |
|---|---|---|
| S06 | `services/hermes-gateway` (Fastify) | Superseded by the Python `gateway_app.py`; never built past scaffold. |
| S06 | `packages/hermes-runtime` (TS stub) | Voided by ADR-0139 (Python `hermes-runtime` is the real one). |
| S11 | `packages/domain-adapters` | Mock drivers for the deleted store path; zero code importers post-S09. |
| S11 | `packages/eval-runner` (TypeScript) | Ran assertions against the deleted mock drivers; never wired into CI; superseded by the live Python `hermes/eval_runner`. |

The TypeScript workspace now ends at `apps/workbench` + `packages/shared`:
one Next.js app and one package of contracts/types shared between it and
nothing else in TS (the Python side consumes the same concepts natively).
Every other workspace member (`services/`, the other `packages/*`) is gone.

## Consequences

- **One backend seam, one thing to keep correct.** A behavior change in a
  Domain Adapter Tool's contract is a Python change plus a `@toee/shared`
  type update if the wire shape moved — never a second mock implementation
  to remember to update.
- **`ToolExecutionContext`/`ToolGate` (the TS Tool Gate hook point) are
  gone.** Per-profile allowlisting and gate enforcement live where the real
  dispatch happens: `hermes-runtime`'s `tool_dispatch_app.py` /
  `tool_dispatch_composition.py`. The `packages/shared/src/tools.ts` catalog
  comment that used to point at `@toee/domain-adapters` now points there.
- **No TS eval harness remains.** `pnpm eval` is gone; eval runs exclusively
  through `hermes/eval_runner` (`uv run python -m eval_runner`), which was
  already the CI gate and the one this repo actually maintains test coverage
  for.
- **A future TS mock-first scaffold, should one ever be wanted again, starts
  from zero.** Nothing is preserved as a template — the mock drivers
  duplicated the real Domain Adapter Tool contracts closely enough that
  resurrecting them from git history is straightforward if ever needed, but
  nothing in the live tree depends on that being possible.
- **No behavior change.** This is a pure deletion of already-dead code plus
  the config lines that named it; the acceptance gate for this slice is CI
  green on the cleaned tree, not a new user-facing capability.

## Considered options

- **Keep `packages/domain-adapters` as a standalone fixture library for
  future TS tests (rejected).** Nothing in the live tree would import it;
  keeping an unreferenced package around is exactly the deferred-cleanup debt
  this track (T3) exists to close, and PAC-5 (S12) is gated on the TS side
  being clean.
- **Extract `ToolExecutionContext` to `@toee/shared` before deleting
  (rejected).** Its only consumer was `packages/eval-runner/src/harness.ts`,
  which is deleted in the same slice — extracting a type for zero remaining
  callers is speculative.
- **Delete `packages/eval-runner` in a separate slice from
  `packages/domain-adapters` (rejected).** They share one deletion reason
  (the store path's mock drivers went away) and one dependency direction
  (`eval-runner`'s `types.ts` imports mock data types from
  `domain-adapters`), so splitting the deletion across two slices would leave
  an intermediate commit with a broken import.

## Verification

Pure-refactor carve-out (per the issue's three-layer gate): full CI green on
the cleaned tree is the acceptance evidence, not a new test.

- `pnpm install` — lockfile regenerates cleanly with both packages gone.
- `cd apps/workbench && npx tsc --noEmit && npx vitest run` — typecheck +
  unit tests green with `@toee/domain-adapters` removed from
  `next.config.ts`/`package.json`.
- `cd hermes-runtime && uv run pytest -q` / `cd hermes && uv run pytest -q`
  — untouched Python suites, unaffected by a TS-only deletion.
- `node scripts/dev-up.mjs --selfcheck` — S10's orchestration script never
  named either package; unaffected.
- Grep-proof: no source, test, or workspace-config reference to
  `@toee/domain-adapters` or the TypeScript `@toee/eval-runner` remains
  anywhere outside ADR/PRD/issue prose (which is history, not live code).
