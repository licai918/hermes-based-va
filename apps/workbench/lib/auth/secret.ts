// Workbench session signing secret (ADR-0018). Node runtime only — reads
// process.env. Edge code (middleware) must NOT import this; instead it calls
// resolveSessionSecret(process.env.WORKBENCH_SESSION_SECRET) directly so both
// runtimes share the same dev fallback (see session-secret.ts). Real deployments
// set WORKBENCH_SESSION_SECRET (GCP Secret Manager).
import { resolveSessionSecret } from "./session-secret";

export function getSessionSecret(): string {
  return resolveSessionSecret(process.env.WORKBENCH_SESSION_SECRET);
}
