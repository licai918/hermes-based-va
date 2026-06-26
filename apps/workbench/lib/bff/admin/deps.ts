// Shared dependency-injection plumbing for the Admin BFF (ADR-0094). Pure handlers
// under this folder receive an AdminDeps so they unit-test against isolated
// in-memory stores + a fabricated session; the thin app/api/admin/* route files
// wire in the real singletons via createAdminDeps. Node runtime only (the account
// spine reaches node:crypto), so every admin route sets runtime nodejs.
import { getAccountStore, type AccountStore } from "../../auth/account-store";
import type { WorkbenchSession } from "../../auth/session";
import { getEvalStore, type EvalStore } from "../../gateway/eval-store";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { resolveProfileApiConfig } from "../../gateway/hermes-api-config";
import {
  getKnowledgeStore,
  type KnowledgeStore,
} from "../../gateway/knowledge-store";

export type AdminDeps = {
  knowledge: KnowledgeStore;
  evalStore: EvalStore;
  accounts: AccountStore;
  session: WorkbenchSession;
  now: number;
};

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

// Real-singleton deps for the route handlers. Node runtime only.
export function createAdminDeps(session: WorkbenchSession): AdminDeps {
  return {
    knowledge: getKnowledgeStore(),
    evalStore: getEvalStore(),
    accounts: getAccountStore(),
    session,
    now: Date.now(),
  };
}

// The per-profile Supervisor Admin API client (ADR-0141), or null when
// HERMES_ADMIN_API_URL/TOKEN are unset (the route then falls back to the in-memory
// store). The acting account is baked in so governed admin writes attribute their
// audit to the real supervisor; reads carry it harmlessly. Built per-request inside
// withSession, mirroring the copilot case routes.
export function createAdminApiClient(
  session: WorkbenchSession,
): HermesApiClient | null {
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_ADMIN_API_URL,
    process.env.HERMES_ADMIN_API_TOKEN,
  );
  if (!apiConfig) return null;
  return new HermesApiClient({ ...apiConfig, actorAccountId: session.accountId });
}
