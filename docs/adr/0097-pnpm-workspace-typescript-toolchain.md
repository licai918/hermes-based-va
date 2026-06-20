# pnpm workspace monorepo toolchain with TypeScript project references

The **Hermes VA** repository uses a pnpm workspace monorepo for `apps/*`, `services/*`, and `packages/*` per ADR-0091.

## Workspace layout

Root files:

- `pnpm-workspace.yaml` — includes `apps/*`, `services/*`, and `packages/*`
- `package.json` — root scripts only; no business runtime code at repo root
- `tsconfig.base.json` — shared compiler defaults

Package dependency order for TypeScript project references:

1. `packages/shared`
2. `packages/domain-adapters`
3. `packages/hermes-runtime`
4. `apps/workbench`
5. `services/hermes-gateway`

Each package keeps its own `package.json` and `tsconfig.json` with references to its upstream packages.

## Root scripts

The root `package.json` exposes shared developer commands, including:

- `dev:workbench`
- `dev:gateway`
- `lint`
- `typecheck`
- `test`

Eval execution may later be added as `eval` without changing the workspace shape.

## Runtime baseline

- Node.js 20 or newer
- TypeScript 5.x
- pnpm as the only supported package manager for this repo in v1

Turborepo or other task orchestration layers are deferred until build times or CI parallelism justify them.

**Considered options:** npm workspaces (rejected—pnpm provides better monorepo deduplication for shared packages); separate package managers per app (rejected—breaks shared package versioning); add Turborepo on day one (rejected—unnecessary complexity for the initial scaffold).
