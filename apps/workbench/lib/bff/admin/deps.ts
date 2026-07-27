// Shared plumbing for the Admin BFF (ADR-0094). API-only since 0.0.4 S09: the
// in-memory knowledge/eval/account stores are gone, so the only per-request
// dependency a handler needs is the Supervisor Admin Profile API client. Node
// runtime only (the account spine reaches node:crypto), so every admin route sets
// runtime nodejs.
import type { WorkbenchSession } from "../../auth/session";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { requireProfileApiConfig } from "../../gateway/hermes-api-config";

// Reads a JSON object body; returns null on parse failure or a non-object payload
// so handlers can map a bad body to their own 400.
export async function readJsonBody(
  req: Request,
): Promise<Record<string, unknown> | null> {
  try {
    const raw = await req.json();
    return typeof raw === "object" && raw !== null
      ? (raw as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

// The per-profile Supervisor Admin API client (ADR-0141). The acting account is
// baked in so governed admin writes attribute their audit to the real supervisor;
// reads carry it harmlessly. Built per-request inside withSession, mirroring the
// copilot case routes. Throws if HERMES_ADMIN_API_URL/TOKEN are unset — which
// instrumentation.ts already refused to boot without (0.0.4 S09, FR-3).
export function createAdminApiClient(session: WorkbenchSession): HermesApiClient {
  return new HermesApiClient({
    ...requireProfileApiConfig("admin"),
    actorAccountId: session.accountId,
  });
}
