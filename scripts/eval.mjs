#!/usr/bin/env node
// Launch Eval Runner entrypoint (stub).
// The real fixture loader, assertion engine, report, and CLI land in slices #7-#8
// (issues #9 and #10). This stub keeps `pnpm eval` wired from the monorepo
// bootstrap (slice #3) without pulling in the runner before its dependencies.
console.log(
  "Launch Eval Runner is not implemented yet. See slices #7-#8 (issues #9, #10).",
);
process.exit(0);
