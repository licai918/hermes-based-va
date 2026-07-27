// Customer Memory preference reads/corrections for the Copilot BFF (ADR-0111/
// 0114, PAC-4 S17). The dispatch server already resolves the customer binding
// from `case_id` (S16), so these handlers only ever pass `case_id` through —
// never a binding key — and the response never carries the `binding_key` the
// dispatch server returns, since that is the customer's raw identity key and
// must not reach the browser. Like every other BFF handler since 0.0.4 S09, this
// is API-only.
import { json, problem } from "../respond";
import { readJsonBody, readNonEmptyString } from "./deps";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { mapPreferences } from "../../gateway/hermes-map";
import { PREFERENCE_SLOTS, type MemoryPreferenceSlot } from "../../gateway/types";

function isPreferenceSlot(value: unknown): value is MemoryPreferenceSlot {
  return (
    typeof value === "string" &&
    (PREFERENCE_SLOTS as readonly string[]).includes(value)
  );
}

// READ, fail-open (dispatch, not dispatchWrite): a rep can view preferences with
// no actor attribution needed.
export async function handleGetPreferencesViaApi(
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  try {
    const data = (await client.dispatch("toee_customer_memory", "get_preferences", {
      case_id: caseId,
    })) as { preferences?: unknown };
    // A missing/malformed `preferences` field is a contract violation, not an
    // empty read -- mapPreferences throws, which the catch below turns into a
    // governed 502 (ADR-0090) instead of silently rendering an empty panel.
    return json({ preferences: mapPreferences(data?.preferences) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleUpsertPreferenceViaApi(
  req: Request,
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  const body = await readJsonBody(req);
  const slot = body?.slot;
  if (!isPreferenceSlot(slot)) {
    return problem(400, "slot must be one of the 4 preference slots");
  }
  const value = readNonEmptyString(body, "value");
  if (!value) return problem(400, "value is required");
  try {
    // dispatchWrite (not dispatch): a governed write must carry the actor
    // (ADR-0141). The dispatch param key is `key`, matching the
    // toee_customer_memory driver's `params.key` contract.
    await client.dispatchWrite("toee_customer_memory", "upsert_preference", {
      case_id: caseId,
      key: slot,
      value,
    });
    // Echo back the validated slot/value rather than the raw dispatch result,
    // which carries binding_key.
    return json({ slot, value, stored: true });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleClearPreferenceViaApi(
  req: Request,
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  const body = await readJsonBody(req);
  const slot = body?.slot;
  if (!isPreferenceSlot(slot)) {
    return problem(400, "slot must be one of the 4 preference slots");
  }
  try {
    await client.dispatchWrite("toee_customer_memory", "clear_preference", {
      case_id: caseId,
      key: slot,
    });
    return json({ slot, cleared: true });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// Dismiss a pending S14 proposal (S15, FR-16/FR-17). Distinct from clear: there
// is no slot to clear (the proposal never persisted), so this dispatches the
// audit-only `dismiss_proposal` action -- it writes a Workbench Audit Log row
// (proposal, decider, timestamp) and NO preference slot (US17). `evidence`
// matches the wire param name upsert_preference already uses (see
// hermes/toee_hermes/drivers/mock/memory.py `_read_evidence`); the browser's
// `evidenceTurn` field name is translated here, not renamed end-to-end.
export async function handleDismissProposalViaApi(
  req: Request,
  client: HermesApiClient,
  caseId: string,
): Promise<Response> {
  const body = await readJsonBody(req);
  const slot = body?.slot;
  if (!isPreferenceSlot(slot)) {
    return problem(400, "slot must be one of the 4 preference slots");
  }
  const value = readNonEmptyString(body, "value");
  if (!value) return problem(400, "value is required");
  const evidence = readNonEmptyString(body, "evidenceTurn") ?? undefined;
  try {
    await client.dispatchWrite("toee_customer_memory", "dismiss_proposal", {
      case_id: caseId,
      key: slot,
      value,
      evidence,
    });
    return json({ slot, dismissed: true });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
