// Shared dependency-injection plumbing for the Copilot BFF (ADR-0094). Pure
// handlers under this folder receive a CopilotDeps so they unit-test against an
// isolated GatewayStore + mock ToolDriver + fabricated session; the thin route
// files wire in the real singletons via createCopilotDeps.
import {
  createDefaultMockDriver,
  type ToolDriver,
  type ToolExecutionContext,
} from "@toee/domain-adapters";
import { HERMES_PROFILES, WORKBENCH_ROLES } from "@toee/shared";
import type { WorkbenchSession } from "../../auth/session";
import { getGatewayStore, type GatewayStore } from "../../gateway/store";
import type { AuditAction, AuditLogEntry } from "../../gateway/types";

export type CopilotDeps = {
  store: GatewayStore;
  driver: ToolDriver;
  session: WorkbenchSession;
  now: number;
};

// Assign + priority are supervisor/admin-only (ADR-0082). `withSession` only
// gates audit/admin route prefixes, so these checks live in the handlers.
export function isSupervisorOrAdmin(session: WorkbenchSession): boolean {
  return (
    session.role === WORKBENCH_ROLES.supervisor ||
    session.role === WORKBENCH_ROLES.admin
  );
}

// Every governed tool call runs under the Internal Copilot Profile (ADR-0035),
// attributed to the acting employee for audit.
export function copilotContext(deps: CopilotDeps): ToolExecutionContext {
  return {
    profile: HERMES_PROFILES.internalCopilot,
    userId: deps.session.accountId,
  };
}

// Appends a Workbench Audit Log entry attributed to the acting employee at the
// injected clock (ADR-0029). Returns the entry for convenience/testing.
export function appendAudit(
  deps: CopilotDeps,
  action: AuditAction,
  fields?: { caseId?: string; recordId?: string; detail?: string },
): AuditLogEntry {
  const entry: AuditLogEntry = {
    entryId: crypto.randomUUID(),
    at: deps.now,
    actorAccountId: deps.session.accountId,
    actorUsername: deps.session.username,
    action,
    ...fields,
  };
  deps.store.appendAuditEntry(entry);
  return entry;
}

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

export function readNonEmptyString(
  body: Record<string, unknown> | null,
  key: string,
): string | null {
  const value = body?.[key];
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

// Real-singleton deps for the route handlers. Node runtime only (the store +
// session spine reach node:crypto), so every copilot route sets runtime nodejs.
export function createCopilotDeps(session: WorkbenchSession): CopilotDeps {
  return {
    store: getGatewayStore(),
    driver: createDefaultMockDriver(),
    session,
    now: Date.now(),
  };
}
