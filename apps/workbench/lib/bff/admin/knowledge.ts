// KnowledgeOps slot handlers for the Admin BFF (ADR-0087 master-detail policy
// authoring over the six Required Operational Policy Slots, ADR-0003). Pure and
// dependency-injected; the thin app/api/admin/knowledge route files wrap these
// with withSession and inject the real KnowledgeStore singleton.
import { HermesApiClient, HermesApiError } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import type { PolicySlot, SlotStatus } from "../../gateway/knowledge-store";
import { json, problem } from "../respond";
import { type AdminDeps, readJsonBody } from "./deps";

export function handleListSlots(deps: AdminDeps): Response {
  return json({ slots: deps.knowledge.listSlots() });
}

export async function handleSaveDraft(
  req: Request,
  slotId: string,
  deps: AdminDeps,
): Promise<Response> {
  const body = await readJsonBody(req);
  const patch: { draftText?: string; owner?: string; reviewDate?: string } = {};
  if (typeof body?.draftText === "string") patch.draftText = body.draftText;
  if (typeof body?.owner === "string") patch.owner = body.owner;
  if (typeof body?.reviewDate === "string") patch.reviewDate = body.reviewDate;

  const slot = deps.knowledge.saveDraft(slotId, patch);
  if (!slot) return problem(404, "slot not found");
  return json({ slot });
}

export function handleSubmitSlot(slotId: string, deps: AdminDeps): Response {
  const result = deps.knowledge.submitForEval(slotId);
  if (result.ok) return json({ slot: result.slot });
  if (result.reason === "not_found") return problem(404, "slot not found");
  return problem(409, "slot has no draft to submit");
}

export function handleRollbackSlot(slotId: string, deps: AdminDeps): Response {
  const result = deps.knowledge.rollbackPublished(slotId);
  if (result.ok) return json({ slot: result.slot });
  if (result.reason === "not_found") return problem(404, "slot not found");
  return problem(409, "slot has no previous published version");
}

// --- Per-profile API cutover (ADR-0141/0145 Increment 6) ---------------------
// The Supervisor Admin knowledge-slot routes dispatch toee_knowledge_ops over the
// per-profile Hermes API when HERMES_ADMIN_API_URL/TOKEN are configured (else the
// in-memory KnowledgeStore). The list read uses dispatch (fail-open); the three
// governed mutations use dispatchWrite (fail-closed on the acting supervisor baked
// into the client), so a write can never land a NULL-actor audit row — the
// datastore enforces the same rule. The per-class error mapping turns a governed
// not_found/conflict into 404/409 (store-path status parity).

const SLOT_STATUSES = new Set<SlotStatus>([
  "empty",
  "draft",
  "pending_eval",
  "published",
  "gap",
]);

// Maps a snake_case workbench_policy_slot row from the per-profile API (ADR-0145)
// onto the wire PolicySlot, rejecting contract violations (missing id/title,
// unknown status) as governed HermesApiErrors so a bad upstream surfaces on the
// ADR-0090 banner rather than rendering garbage (mirrors mapPublicAccount).
export function mapPolicySlot(raw: unknown): PolicySlot {
  if (typeof raw !== "object" || raw === null) {
    throw new HermesApiError("unexpected_error", "malformed policy slot payload");
  }
  const r = raw as Record<string, unknown>;
  const slotId = typeof r.slot_id === "string" ? r.slot_id : "";
  if (!slotId) throw new HermesApiError("unexpected_error", "missing slot id");
  if (typeof r.title !== "string" || r.title.length === 0) {
    throw new HermesApiError("unexpected_error", "missing slot title");
  }
  if (typeof r.status !== "string" || !SLOT_STATUSES.has(r.status as SlotStatus)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown slot status: ${String(r.status)}`,
    );
  }
  // draft_text/published_text/owner/review_date are nullable; a provided string
  // (incl. "") is preserved, anything else is null — store-path parity.
  const orNull = (v: unknown): string | null => (typeof v === "string" ? v : null);
  return {
    slotId,
    title: r.title,
    status: r.status as SlotStatus,
    draftText: orNull(r.draft_text),
    publishedText: orNull(r.published_text),
    owner: orNull(r.owner),
    reviewDate: orNull(r.review_date),
    hasGapPrompt: r.has_gap_prompt === true,
  };
}

export async function handleListSlotsViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = (await client.dispatch(
      "toee_knowledge_ops",
      "get_policy_slots",
    )) as { slots?: unknown };
    const rows = Array.isArray(data?.slots) ? data.slots : [];
    return json({ slots: rows.map(mapPolicySlot) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleSaveDraftViaApi(
  req: Request,
  slotId: string,
  client: HermesApiClient,
): Promise<Response> {
  const body = await readJsonBody(req);
  // Same provided-field semantics as the store path: only forward present fields,
  // mapped to the snake_case the datastore reads.
  const params: Record<string, unknown> = { slot_id: slotId };
  if (typeof body?.draftText === "string") params.draft_text = body.draftText;
  if (typeof body?.owner === "string") params.owner = body.owner;
  if (typeof body?.reviewDate === "string") params.review_date = body.reviewDate;
  try {
    const result = (await client.dispatchWrite(
      "toee_knowledge_ops",
      "update_policy_slot",
      params,
    )) as { slot?: unknown };
    return json({ slot: mapPolicySlot(result.slot) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleSubmitSlotViaApi(
  slotId: string,
  client: HermesApiClient,
): Promise<Response> {
  try {
    const result = (await client.dispatchWrite(
      "toee_knowledge_ops",
      "submit_for_eval",
      { slot_id: slotId },
    )) as { slot?: unknown };
    return json({ slot: mapPolicySlot(result.slot) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleRollbackSlotViaApi(
  slotId: string,
  client: HermesApiClient,
): Promise<Response> {
  try {
    const result = (await client.dispatchWrite(
      "toee_knowledge_ops",
      "rollback_published_policy",
      { slot_id: slotId },
    )) as { slot?: unknown };
    return json({ slot: mapPolicySlot(result.slot) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
