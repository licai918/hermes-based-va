// Per-profile Hermes API config resolution (ADR-0141). Pure like
// session-secret.ts: the env object is injectable so this stays unit-testable and
// runtime-agnostic.
//
// 0.0.4 S09 (FR-1/FR-3): the workbench is API-only. There is no in-memory store to
// fall back to any more, so an unset URL/token is a CONFIGURATION ERROR, not a
// silent downgrade to a fake backend — `assertHermesApiConfig` runs from
// instrumentation.ts and refuses to boot, naming every variable that is missing.
export interface ProfileApiConfig {
  baseUrl: string;
  token: string;
}

// The two per-profile backends the workbench BFF talks to: the Internal Copilot
// Profile (case reads/writes, drafts, chat, memory) and the Supervisor Admin
// Profile (accounts, knowledge, eval, job queue).
export const HERMES_API_ENV = {
  copilot: { url: "HERMES_COPILOT_API_URL", token: "HERMES_COPILOT_API_TOKEN" },
  admin: { url: "HERMES_ADMIN_API_URL", token: "HERMES_ADMIN_API_TOKEN" },
} as const;

export type HermesApiProfile = keyof typeof HERMES_API_ENV;

type Env = Record<string, string | undefined>;

function missingVars(profile: HermesApiProfile, env: Env): string[] {
  const names = HERMES_API_ENV[profile];
  return [names.url, names.token].filter((name) => {
    const value = env[name];
    return value === undefined || value.length === 0;
  });
}

function configurationError(missing: string[]): Error {
  return new Error(
    `Hermes API configuration missing: ${missing.join(", ")}. ` +
      "The workbench is API-only (0.0.4 S09) — every BFF route reads and writes " +
      "through the per-profile Hermes API, and there is no in-memory fallback to " +
      "degrade to. Set these in apps/workbench/.env.local (see docs/ops/local-e2e.md).",
  );
}

// The config for one profile, or a throw naming exactly which of its two variables
// are unset. Callers are route handlers that run after `assertHermesApiConfig` has
// already passed at boot, so in practice this never throws in a booted server.
export function requireProfileApiConfig(
  profile: HermesApiProfile,
  env: Env = process.env,
): ProfileApiConfig {
  const missing = missingVars(profile, env);
  if (missing.length > 0) throw configurationError(missing);
  const names = HERMES_API_ENV[profile];
  return { baseUrl: env[names.url] as string, token: env[names.token] as string };
}

// Boot gate (FR-3): fail closed on ANY missing variable, reporting all of them in
// one message rather than one per restart.
export function assertHermesApiConfig(env: Env = process.env): void {
  const missing = (Object.keys(HERMES_API_ENV) as HermesApiProfile[]).flatMap(
    (profile) => missingVars(profile, env),
  );
  if (missing.length > 0) throw configurationError(missing);
}
