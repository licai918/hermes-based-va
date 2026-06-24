// Case queue reads + governed case writes for the Copilot BFF (ADR-0094). Pure,
// dependency-injected handlers: the route files wrap them with withSession and
// inject createCopilotDeps. Reads are open to any authenticated copilot user;
// assign + priority are supervisor/admin-only (ADR-0082).
import { json, problem } from "../respond";
import {
  appendAudit,
  isSupervisorOrAdmin,
  readJsonBody,
  readNonEmptyString,
  type CopilotDeps,
} from "./deps";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import type {
  AssigneeFilterMode,
  CaseListFilter,
  CaseStatus,
} from "../../gateway/types";

const VALID_STATUSES: readonly CaseStatus[] = [
  "open",
  "in_progress",
  "resolved",
];
const VALID_MODES: readonly AssigneeFilterMode[] = [
  "all",
  "mine",
  "unassigned",
  "mine_or_unassigned",
];
const DEFAULT_STATUSES: CaseStatus[] = ["open", "in_progress"];

const CASE_NOT_FOUND = "case not found";

function parseStatuses(url: URL): CaseStatus[] | null {
  const raw = url.searchParams
    .getAll("status")
    .flatMap((value) => value.split(","))
    .map((value) => value.trim());
  const valid = raw.filter((value): value is CaseStatus =>
    (VALID_STATUSES as readonly string[]).includes(value),
  );
  return valid.length > 0 ? valid : null;
}

// Builds the queue filter from query params, defaulting per role when params are
// absent: reps see mine_or_unassigned, supervisors/admins see all (ADR-0079).
// Exported so the per-profile API path (ADR-0141) derives the identical filter.
export function buildCaseListFilter(url: URL, deps: CopilotDeps): CaseListFilter {
  const statuses = parseStatuses(url) ?? DEFAULT_STATUSES;
  const modeRaw = url.searchParams.get("assignee");
  const accountId = deps.session.accountId;

  let assignee: CaseListFilter["assignee"];
  if (modeRaw && (VALID_MODES as readonly string[]).includes(modeRaw)) {
    const mode = modeRaw as AssigneeFilterMode;
    assignee =
      mode === "mine" || mode === "mine_or_unassigned"
        ? { mode, accountId }
        : { mode };
  } else if (isSupervisorOrAdmin(deps.session)) {
    assignee = { mode: "all" };
  } else {
    assignee = { mode: "mine_or_unassigned", accountId };
  }

  return { statuses, assignee };
}

export function handleListCases(req: Request, deps: CopilotDeps): Response {
  const filter = buildCaseListFilter(new URL(req.url), deps);
  return json({ cases: deps.store.listCases(filter) });
}

// Per-profile API variant of the queue read (ADR-0141): same role-derived filter,
// but the cases come from the Internal Copilot Profile's deterministic
// `tools:dispatch` over HTTP instead of the in-memory store. The route picks this
// path only when HERMES_COPILOT_API_URL/TOKEN are configured.
export async function handleListCasesViaApi(
  req: Request,
  client: HermesApiClient,
  deps: CopilotDeps,
): Promise<Response> {
  const filter = buildCaseListFilter(new URL(req.url), deps);
  try {
    const cases = await client.listCases(filter as unknown as Record<string, unknown>);
    return json({ cases });
  } catch {
    // ponytail: the tracer collapses any upstream failure (transport or governed
    // tool error) to a 502 so ADR-0090's global error banner surfaces it; per-class
    // handling (e.g. distinguishing policy_blocked) lands with the full migration.
    return problem(502, "case service unavailable");
  }
}

export function handleGetCase(caseId: string, deps: CopilotDeps): Response {
  const found = deps.store.getCase(caseId);
  if (!found) return problem(404, CASE_NOT_FOUND);
  return json({ case: found });
}

export function handleGetThread(caseId: string, deps: CopilotDeps): Response {
  const found = deps.store.getCase(caseId);
  if (!found) return problem(404, CASE_NOT_FOUND);
  const messages = deps.store.getThread(caseId);
  appendAudit(deps, "case_view", { caseId });
  return json({ case: found, messages });
}

export function handleGetAuditLog(caseId: string, deps: CopilotDeps): Response {
  const found = deps.store.getCase(caseId);
  if (!found) return problem(404, CASE_NOT_FOUND);
  return json({ entries: deps.store.getCaseAuditLog(caseId) });
}

export function handleClaim(caseId: string, deps: CopilotDeps): Response {
  const found = deps.store.getCase(caseId);
  if (!found) return problem(404, CASE_NOT_FOUND);
  const accountId = deps.session.accountId;
  if (found.assigneeAccountId !== null && found.assigneeAccountId !== accountId) {
    return problem(409, "case already assigned to another account");
  }
  const updated = deps.store.claimCase(caseId, accountId);
  appendAudit(deps, "claim_case", { caseId });
  return json({ case: updated });
}

export async function handleAssign(
  req: Request,
  caseId: string,
  deps: CopilotDeps,
): Promise<Response> {
  if (!isSupervisorOrAdmin(deps.session)) return problem(403, "forbidden");
  const body = await readJsonBody(req);
  const assigneeAccountId = readNonEmptyString(body, "assigneeAccountId");
  if (!assigneeAccountId) return problem(400, "assigneeAccountId is required");
  if (!deps.store.getCase(caseId)) return problem(404, CASE_NOT_FOUND);
  const updated = deps.store.assignCase(caseId, assigneeAccountId);
  appendAudit(deps, "assign_case", { caseId, detail: assigneeAccountId });
  return json({ case: updated });
}

export function handleResolve(caseId: string, deps: CopilotDeps): Response {
  if (!deps.store.getCase(caseId)) return problem(404, CASE_NOT_FOUND);
  const updated = deps.store.resolveCase(caseId, deps.session.accountId);
  appendAudit(deps, "resolve_case", { caseId });
  return json({ case: updated });
}

export async function handlePriority(
  req: Request,
  caseId: string,
  deps: CopilotDeps,
): Promise<Response> {
  if (!isSupervisorOrAdmin(deps.session)) return problem(403, "forbidden");
  const body = await readJsonBody(req);
  const urgent = body?.urgent;
  if (typeof urgent !== "boolean") return problem(400, "urgent must be a boolean");
  if (!deps.store.getCase(caseId)) return problem(404, CASE_NOT_FOUND);
  const updated = deps.store.updatePriority(caseId, urgent);
  appendAudit(deps, "update_priority", { caseId, detail: String(urgent) });
  return json({ case: updated });
}

export async function handleContactReason(
  req: Request,
  caseId: string,
  deps: CopilotDeps,
): Promise<Response> {
  const body = await readJsonBody(req);
  const contactReason = readNonEmptyString(body, "contactReason");
  if (!contactReason) return problem(400, "contactReason is required");
  if (!deps.store.getCase(caseId)) return problem(404, CASE_NOT_FOUND);
  const updated = deps.store.updateContactReason(caseId, contactReason);
  appendAudit(deps, "update_contact_reason", { caseId, detail: contactReason });
  return json({ case: updated });
}
