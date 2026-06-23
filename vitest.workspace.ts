// Vitest monorepo workspace: the root config covers the pure TS packages in a
// node environment; the workbench config runs its React + BFF tests in jsdom.
// A single `pnpm test` (vitest run) executes both projects.
export default ["./vitest.config.ts", "./apps/workbench/vitest.config.ts"];
