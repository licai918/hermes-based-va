// Next.js boot hook. 0.0.4 S09 (FR-3): the workbench is API-only, so a missing
// HERMES_*_API_URL/TOKEN must stop the server here rather than surface as a broken
// panel on the first request — there is no in-memory store left to degrade to.
//
// `env` is injectable (default `process.env`) so the decision is unit-testable
// without a real Next boot -- same pattern as hermes-api-config.ts. Next calls
// `register()` with no arguments, so this default is the only path production
// ever takes; behavior is unchanged from the plain `process.env` reads this
// replaced (0.0.4 S09 fix wave 1, finding 2).
export async function register(
  env: Record<string, string | undefined> = process.env,
): Promise<void> {
  // The edge runtime (middleware) never talks to the Hermes API, and `next build`
  // compiles without production credentials.
  if (env.NEXT_RUNTIME !== "nodejs") return;
  if (env.NEXT_PHASE === "phase-production-build") return;
  const { assertHermesApiConfig } = await import("./lib/gateway/hermes-api-config");
  assertHermesApiConfig(env);
}
