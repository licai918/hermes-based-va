// Shared plumbing for the Copilot BFF (ADR-0094). API-only since 0.0.4 S09: the
// in-memory GatewayStore and the mock ToolDriver are gone, so handlers take the
// acting `WorkbenchSession` directly plus a per-profile client the route builds
// here. Node runtime only (the session spine reaches node:crypto), so every
// copilot route sets runtime nodejs.
import { WORKBENCH_ROLES } from "@toee/shared";
import type { WorkbenchSession } from "../../auth/session";
import { HermesAgentClient } from "../../gateway/hermes-agent-client";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { requireProfileApiConfig } from "../../gateway/hermes-api-config";

// Assign + priority are supervisor/admin-only (ADR-0082). `withSession` only
// gates audit/admin route prefixes, so these checks live in the handlers.
export function isSupervisorOrAdmin(session: WorkbenchSession): boolean {
  return (
    session.role === WORKBENCH_ROLES.supervisor ||
    session.role === WORKBENCH_ROLES.admin
  );
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

// The Internal Copilot Profile clients (ADR-0141/0147), acting account baked in so
// every governed dispatch and agent turn attributes its audit to the real employee.
// Both throw if HERMES_COPILOT_API_URL/TOKEN are unset — which instrumentation.ts
// already refused to boot without (0.0.4 S09, FR-3).
export function createCopilotApiClient(session: WorkbenchSession): HermesApiClient {
  return new HermesApiClient({
    ...requireProfileApiConfig("copilot"),
    actorAccountId: session.accountId,
  });
}

export function createCopilotAgentClient(
  session: WorkbenchSession,
): HermesAgentClient {
  return new HermesAgentClient({
    ...requireProfileApiConfig("copilot"),
    actorAccountId: session.accountId,
  });
}
