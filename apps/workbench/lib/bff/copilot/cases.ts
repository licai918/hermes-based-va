// Case queue reads + governed case writes for the Copilot BFF (ADR-0094). Pure,
// dependency-injected handlers: the route files wrap them with withSession and
// inject the Internal Copilot Profile API client. Reads are open to any
// authenticated copilot user; assign + priority are supervisor/admin-only
// (ADR-0082). API-only since 0.0.4 S09 — the datastore is the single system of
// record for cases, threads, claims and the Workbench Audit Log.
import { json, problem } from "../respond";
import {
  isSupervisorOrAdmin,
  readJsonBody,
  readNonEmptyString,
} from "./deps";
import type { WorkbenchSession } from "../../auth/session";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import {
  mapAuditEntry,
  mapThreadMessage,
  mapWorkbenchCase,
} from "../../gateway/hermes-map";
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
// absent: reps see mine_or_unassigned, supervisors/admins see all (ADR-0079). The
// datastore applies the filter; this is the only place the role default is decided.
export function buildCaseListFilter(
  url: URL,
  session: WorkbenchSession,
): CaseListFilter {
  const statuses = parseStatuses(url) ?? DEFAULT_STATUSES;
  const modeRaw = url.searchParams.get("assignee");
  const accountId = session.accountId;

  let assignee: CaseListFilter["assignee"];
  if (modeRaw && (VALID_MODES as readonly string[]).includes(modeRaw)) {
    const mode = modeRaw as AssigneeFilterMode;
    assignee =
      mode === "mine" || mode === "mine_or_unassigned"
        ? { mode, accountId }
        : { mode };
  } else if (isSupervisorOrAdmin(session)) {
    assignee = { mode: "all" };
  } else {
    assignee = { mode: "mine_or_unassigned", accountId };
  }

  return { statuses, assignee };
}

// The queue read (ADR-0141): the role-derived filter goes to the Internal Copilot
// Profile's deterministic `tools:dispatch` over HTTP.
export async function handleListCasesViaApi(
  req: Request,
  client: HermesApiClient,
  session: WorkbenchSession,
): Promise<Response> {
  const filter = buildCaseListFilter(new URL(req.url), session);
  try {
    const data = (await client.dispatch(
      "toee_workbench_read",
      "list_cases",
      filter as unknown as Record<string, unknown>,
    )) as { cases?: unknown };
    const rows = Array.isArray(data?.cases) ? data.cases : [];
    // Map + validate each snake_case datastore row onto WorkbenchCase (ADR-0070).
    return json({ cases: rows.map(mapWorkbenchCase) });
  } catch (err) {
    // Surface transport/governed tool failures on the ADR-0090 error banner with
    // the ADR-0104 per-class status (policy_blocked -> 403, vendor_timeout -> 504,
    // ...) instead of the tracer's blanket 502.
    return hermesErrorToProblem(err);
  }
}

// The single-case read (ADR-0141): the case comes from the Internal Copilot
// Profile's get_case dispatch, mapped + validated onto the WorkbenchCase shape. A
// null payload is a legitimate empty read -> 404 (ADR-0020).
export async function handleGetCaseViaApi(
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  try {
    const data = (await client.dispatch("toee_workbench_read", "get_case", {
      case_id: caseId,
    })) as { case?: unknown };
    if (!data || data.case == null) return problem(404, CASE_NOT_FOUND);
    return json({ case: mapWorkbenchCase(data.case) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// The Case Thread Context read (ADR-0082/0141): the case + its read-only timeline
// come from the Internal Copilot Profile's get_thread dispatch, which also writes
// the case_view audit entry (ADR-0042) in the same transaction. A null case is a
// legitimate empty read -> 404 (ADR-0020).
export async function handleGetThreadViaApi(
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  try {
    const data = (await client.dispatch("toee_workbench_read", "get_thread", {
      case_id: caseId,
    })) as { case?: unknown; messages?: unknown };
    if (!data || data.case == null) return problem(404, CASE_NOT_FOUND);
    const rows = Array.isArray(data.messages) ? data.messages : [];
    return json({
      case: mapWorkbenchCase(data.case),
      messages: rows.map(mapThreadMessage),
    });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// The case audit-log read (ADR-0141). Confirms the case exists first so an unknown
// case 404s, then maps the audit rows (with the joined actor username) onto
// AuditLogEntry.
export async function handleGetAuditLogViaApi(
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  try {
    const caseData = (await client.dispatch("toee_workbench_read", "get_case", {
      case_id: caseId,
    })) as { case?: unknown };
    if (!caseData || caseData.case == null) return problem(404, CASE_NOT_FOUND);
    const data = (await client.dispatch("toee_workbench_read", "get_audit_log", {
      case_id: caseId,
    })) as { entries?: unknown };
    const rows = Array.isArray(data?.entries) ? data.entries : [];
    return json({ entries: rows.map(mapAuditEntry) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// --- Governed case writes (ADR-0141 Increment 3) -----------------------------
// Each pre-reads get_case so a missing case 404s (the datastore raises on a
// missing case, which would otherwise surface as a 502), then dispatches the
// toee_case_manage action — attributed to the acting account baked into the client
// (ADR-0141) — and renders the fresh WorkbenchCase the handler returns. Role/body
// validation runs before any dispatch.

// The raw datastore case row, or null when the case does not exist (ADR-0020 empty
// read). Throws HermesApiError on a governed/transport failure (caught by callers).
export async function dispatchGetCaseData(
  client: HermesApiClient,
  caseId: string,
): Promise<unknown | null> {
  const data = (await client.dispatch("toee_workbench_read", "get_case", {
    case_id: caseId,
  })) as { case?: unknown };
  return data && data.case != null ? data.case : null;
}

// Maps the fresh case a mutation returns onto the WorkbenchCase response shape.
function mappedCaseResponse(result: unknown): Response {
  const data = (result ?? {}) as { case?: unknown };
  return json({ case: mapWorkbenchCase(data.case) });
}

export async function handleClaimViaApi(
  client: HermesApiClient,
  caseId: string,
  session: WorkbenchSession,
): Promise<Response> {
  try {
    const current = await dispatchGetCaseData(client, caseId);
    if (current == null) return problem(404, CASE_NOT_FOUND);
    // 409: another account already holds the case.
    const accountId = session.accountId;
    const held = mapWorkbenchCase(current).assigneeAccountId;
    if (held !== null && held !== accountId) {
      return problem(409, "case already assigned to another account");
    }
    // dispatchWrite (not dispatch): a governed write must carry the actor. The
    // datastore is the authoritative conflict gate (the pre-read above is just a
    // fast 404/409 path); a race that slips past it surfaces as a governed
    // `conflict` -> 409 through the catch below.
    const result = await client.dispatchWrite("toee_case_manage", "claim_case", {
      case_id: caseId,
    });
    return mappedCaseResponse(result);
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleAssignViaApi(
  req: Request,
  client: HermesApiClient,
  caseId: string,
  session: WorkbenchSession,
): Promise<Response> {
  if (!isSupervisorOrAdmin(session)) return problem(403, "forbidden");
  const body = await readJsonBody(req);
  const assigneeAccountId = readNonEmptyString(body, "assigneeAccountId");
  if (!assigneeAccountId) return problem(400, "assigneeAccountId is required");
  try {
    if ((await dispatchGetCaseData(client, caseId)) == null) {
      return problem(404, CASE_NOT_FOUND);
    }
    const result = await client.dispatchWrite("toee_case_manage", "assign_case", {
      case_id: caseId,
      assignee_id: assigneeAccountId,
    });
    return mappedCaseResponse(result);
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleResolveViaApi(
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  try {
    if ((await dispatchGetCaseData(client, caseId)) == null) {
      return problem(404, CASE_NOT_FOUND);
    }
    const result = await client.dispatchWrite("toee_case_manage", "resolve_case", {
      case_id: caseId,
    });
    return mappedCaseResponse(result);
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handlePriorityViaApi(
  req: Request,
  client: HermesApiClient,
  caseId: string,
  session: WorkbenchSession,
): Promise<Response> {
  if (!isSupervisorOrAdmin(session)) return problem(403, "forbidden");
  const body = await readJsonBody(req);
  const urgent = body?.urgent;
  if (typeof urgent !== "boolean") return problem(400, "urgent must be a boolean");
  try {
    if ((await dispatchGetCaseData(client, caseId)) == null) {
      return problem(404, CASE_NOT_FOUND);
    }
    // The wire carries a boolean `urgent`; the datastore stores a free urgency
    // label that _read_model maps back to urgent (ADR-0064). Map
    // true->urgent / false->normal.
    const result = await client.dispatchWrite("toee_case_manage", "update_priority", {
      case_id: caseId,
      priority: urgent ? "urgent" : "normal",
    });
    return mappedCaseResponse(result);
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleContactReasonViaApi(
  req: Request,
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  const body = await readJsonBody(req);
  const contactReason = readNonEmptyString(body, "contactReason");
  if (!contactReason) return problem(400, "contactReason is required");
  try {
    if ((await dispatchGetCaseData(client, caseId)) == null) {
      return problem(404, CASE_NOT_FOUND);
    }
    const result = await client.dispatchWrite(
      "toee_case_manage",
      "update_contact_reason",
      { case_id: caseId, contact_reason: contactReason },
    );
    return mappedCaseResponse(result);
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
