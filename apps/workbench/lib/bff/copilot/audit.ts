// Read-only supervisor/admin audit views for the Copilot BFF (ADR-0094): the
// auto-handled audit list/detail (ADR-0037/0085/0086) and the sales-outreach
// list/detail (ADR-0046/0050). Route prefix /api/copilot/audit is gated to
// supervisor/admin by withSession; opening a detail records an audit_view entry
// so supervisors leave an attributable trail (ADR-0029/0037).
import { json, problem } from "../respond";
import { appendAudit, type CopilotDeps } from "./deps";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import {
  mapAutoHandledRecord,
  mapWorkbenchCase,
} from "../../gateway/hermes-map";

const AUTO_HANDLED_NOT_FOUND = "auto-handled record not found";
const SALES_OUTREACH_NOT_FOUND = "sales-outreach case not found";

export function handleListAutoHandled(deps: CopilotDeps): Response {
  return json({ records: deps.store.listAutoHandled() });
}

export async function handleListAutoHandledViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = (await client.dispatch(
      "toee_workbench_read",
      "list_auto_handled",
      {},
    )) as { records?: unknown };
    const rows = Array.isArray(data?.records) ? data.records : [];
    return json({ records: rows.map(mapAutoHandledRecord) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export function handleGetAutoHandled(
  recordId: string,
  deps: CopilotDeps,
): Response {
  const record = deps.store.getAutoHandled(recordId);
  if (!record) return problem(404, AUTO_HANDLED_NOT_FOUND);
  appendAudit(deps, "audit_view", { recordId });
  return json({ record });
}

export async function handleGetAutoHandledViaApi(
  client: HermesApiClient,
  recordId: string,
): Promise<Response> {
  try {
    const data = (await client.dispatch("toee_workbench_read", "get_auto_handled", {
      record_id: recordId,
    })) as { record?: unknown };
    if (!data || data.record == null) {
      return problem(404, AUTO_HANDLED_NOT_FOUND);
    }
    return json({ record: mapAutoHandledRecord(data.record) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export function handleListSalesOutreach(deps: CopilotDeps): Response {
  return json({ cases: deps.store.listSalesOutreach() });
}

export async function handleListSalesOutreachViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = (await client.dispatch(
      "toee_workbench_read",
      "list_sales_outreach",
      {},
    )) as { cases?: unknown };
    const rows = Array.isArray(data?.cases) ? data.cases : [];
    return json({ cases: rows.map(mapWorkbenchCase) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export function handleGetSalesOutreach(
  caseId: string,
  deps: CopilotDeps,
): Response {
  const found = deps.store.getSalesOutreach(caseId);
  if (!found) return problem(404, SALES_OUTREACH_NOT_FOUND);
  appendAudit(deps, "audit_view", { caseId });
  return json({ case: found });
}

export async function handleGetSalesOutreachViaApi(
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  try {
    const data = (await client.dispatch("toee_workbench_read", "get_sales_outreach", {
      case_id: caseId,
    })) as { case?: unknown };
    if (!data || data.case == null) {
      return problem(404, SALES_OUTREACH_NOT_FOUND);
    }
    return json({ case: mapWorkbenchCase(data.case) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
