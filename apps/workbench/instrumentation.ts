// Next.js boot hook. 0.0.4 S09 (FR-3): the workbench is API-only, so a missing
// HERMES_*_API_URL/TOKEN must stop the server here rather than surface as a broken
// panel on the first request — there is no in-memory store left to degrade to.
export async function register(): Promise<void> {
  // The edge runtime (middleware) never talks to the Hermes API, and `next build`
  // compiles without production credentials.
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if (process.env.NEXT_PHASE === "phase-production-build") return;
  const { assertHermesApiConfig } = await import("./lib/gateway/hermes-api-config");
  assertHermesApiConfig();
}
