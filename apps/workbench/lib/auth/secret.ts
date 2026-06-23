// Workbench session signing secret (ADR-0018). Node runtime only — reads
// process.env. Edge code must not import this; pass the secret in explicitly.

// dev only: fallback so local dev works without configuring a secret. Real
// deployments set WORKBENCH_SESSION_SECRET (GCP Secret Manager).
const DEV_SESSION_SECRET = "workbench-dev-session-secret-change-me";

export function getSessionSecret(): string {
  const fromEnv = process.env.WORKBENCH_SESSION_SECRET;
  return fromEnv && fromEnv.length > 0 ? fromEnv : DEV_SESSION_SECRET;
}
