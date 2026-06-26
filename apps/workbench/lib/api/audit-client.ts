// Browser-side client for the read-only supervisor audit BFF routes
// (ADR-0037/0085/0086 auto-handled, ADR-0050 sales-outreach). All four calls are
// GETs that ride the session cookie via getJson and surface a typed ApiError on
// non-2xx (e.g. 404) so views can render a friendly not-found state.
import type { AutoHandledRecord, WorkbenchCase } from "@/lib/gateway/types";
import { getJson } from "./http";

const BASE = "/api/copilot/audit";

export function listAutoHandled(): Promise<{ records: AutoHandledRecord[] }> {
  return getJson<{ records: AutoHandledRecord[] }>(`${BASE}/auto-handled`);
}

export function getAutoHandled(
  recordId: string,
): Promise<{ record: AutoHandledRecord }> {
  return getJson<{ record: AutoHandledRecord }>(
    `${BASE}/auto-handled/${encodeURIComponent(recordId)}`,
  );
}

export function listSalesOutreach(): Promise<{ cases: WorkbenchCase[] }> {
  return getJson<{ cases: WorkbenchCase[] }>(`${BASE}/sales-outreach`);
}

export function getSalesOutreach(
  caseId: string,
): Promise<{ case: WorkbenchCase }> {
  return getJson<{ case: WorkbenchCase }>(
    `${BASE}/sales-outreach/${encodeURIComponent(caseId)}`,
  );
}
