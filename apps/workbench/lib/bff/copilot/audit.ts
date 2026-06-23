// Read-only supervisor/admin audit views for the Copilot BFF (ADR-0094): the
// auto-handled audit list/detail (ADR-0037/0085/0086) and the sales-outreach
// list/detail (ADR-0046/0050). Route prefix /api/copilot/audit is gated to
// supervisor/admin by withSession; opening a detail records an audit_view entry
// so supervisors leave an attributable trail (ADR-0029/0037).
import { json, problem } from "../respond";
import { appendAudit, type CopilotDeps } from "./deps";

export function handleListAutoHandled(deps: CopilotDeps): Response {
  return json({ records: deps.store.listAutoHandled() });
}

export function handleGetAutoHandled(
  recordId: string,
  deps: CopilotDeps,
): Response {
  const record = deps.store.getAutoHandled(recordId);
  if (!record) return problem(404, "auto-handled record not found");
  appendAudit(deps, "audit_view", { recordId });
  return json({ record });
}

export function handleListSalesOutreach(deps: CopilotDeps): Response {
  return json({ cases: deps.store.listSalesOutreach() });
}

export function handleGetSalesOutreach(
  caseId: string,
  deps: CopilotDeps,
): Response {
  const found = deps.store.getSalesOutreach(caseId);
  if (!found) return problem(404, "sales-outreach case not found");
  appendAudit(deps, "audit_view", { caseId });
  return json({ case: found });
}
