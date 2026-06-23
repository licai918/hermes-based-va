// KnowledgeOps slot handlers for the Admin BFF (ADR-0087 master-detail policy
// authoring over the six Required Operational Policy Slots, ADR-0003). Pure and
// dependency-injected; the thin app/api/admin/knowledge route files wrap these
// with withSession and inject the real KnowledgeStore singleton.
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
