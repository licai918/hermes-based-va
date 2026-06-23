// Edge-safe session-secret resolution shared by Node (secret.ts) and Edge
// (middleware.ts). Pure: it does NOT read process.env and uses no Node APIs —
// each caller passes the raw env value so the identical dev fallback signs and
// verifies tokens consistently across both runtimes (a mismatch would make
// login-issued cookies fail middleware verification).
export const DEV_SESSION_SECRET = "workbench-dev-session-secret-change-me";

export function resolveSessionSecret(envValue: string | undefined): string {
  return envValue && envValue.length > 0 ? envValue : DEV_SESSION_SECRET;
}
