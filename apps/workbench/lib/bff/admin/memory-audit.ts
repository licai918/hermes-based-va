// Supervisor Memory Audit View read handler (0.0.3 S20, FR-20) for the Admin BFF
// (ADR-0093 admin route group). Pure and dependency-injected like the sibling
// admin/*.ts modules; the thin app/api/admin/memory-audit route wraps this with
// withSession + a per-profile client.
//
// Dispatches over the Internal Copilot Profile API (HERMES_COPILOT_API_URL/
// TOKEN), NOT the Supervisor Admin Profile API createAdminApiClient (deps.ts)
// uses elsewhere in this folder: toee_customer_memory is allowlisted for
// internal_copilot (and customer_service_external), never for supervisor_admin
// (hermes/toee_hermes/plugin/profiles.py) -- so this is the one admin surface
// that reaches a different per-profile backend than its knowledge/eval/accounts
// siblings. Admin-gating (ADR-0093) still comes from the BFF route itself
// (/api/admin/* + withSession's role check), not from which Hermes profile
// answers the dispatch. The Clear action reuses handleClearPreferenceViaApi
// (lib/bff/copilot/preferences.ts) directly -- same governed clear_preference
// dispatch the copilot correction flow uses, no new write path.
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { mapMemoryAuditView } from "../../gateway/hermes-map";
import { json } from "../respond";

// READ, fail-open (dispatch, not dispatchWrite): a supervisor can view the
// audit trail with no actor attribution needed, same convention as
// handleGetPreferencesViaApi.
export async function handleGetMemoryAuditViaApi(
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  try {
    const data = await client.dispatch("toee_customer_memory", "get_memory_audit", {
      case_id: caseId,
    });
    return json(mapMemoryAuditView(data));
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// 0.0.5 S11 (FR-13, US7): the whole-binding erase. dispatchWrite, never
// dispatch: the action fails closed without an attributed administrator, and
// the 4+1 audit rows are attributed to exactly the actor this asserts. The
// confirm gate is the console's inline confirm dialog (the brief's "one-click
// button (confirm dialog)"), not a server-side propose->confirm pair -- NFR-3
// governs memory CONTENT written by scores and sweeps, and this writes none.
//
// The response is counts only. The dispatch result names every binding key the
// erase touched -- the verified one plus each linked channel's provisional key
// (D10) -- and those are the customer's raw identity: a Shopify id, a phone, an
// email address. Same rule the copilot preferences handlers already follow.
export async function handleEraseCustomerMemoryViaApi(
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  try {
    const data = (await client.dispatchWrite(
      "toee_customer_memory",
      "erase_customer_memory",
      { case_id: caseId },
    )) as { cleared?: unknown; bindings?: unknown[] };
    return json({
      erased: true,
      clearedSlots: typeof data?.cleared === "number" ? data.cleared : 0,
      bindingsCleared: Array.isArray(data?.bindings) ? data.bindings.length : 0,
    });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
