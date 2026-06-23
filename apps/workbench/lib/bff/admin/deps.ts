// Shared dependency-injection plumbing for the Admin BFF (ADR-0094). Pure handlers
// under this folder receive an AdminDeps so they unit-test against isolated
// in-memory stores + a fabricated session; the thin app/api/admin/* route files
// wire in the real singletons via createAdminDeps. Node runtime only (the account
// spine reaches node:crypto), so every admin route sets runtime nodejs.
import { getAccountStore, type AccountStore } from "../../auth/account-store";
import type { WorkbenchSession } from "../../auth/session";
import { getEvalStore, type EvalStore } from "../../gateway/eval-store";
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
