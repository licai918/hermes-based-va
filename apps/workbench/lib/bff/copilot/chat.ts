// Copilot Gateway conversation (ADR-0081). STUBBED: this slice ships a fully
// deterministic acknowledgement with no network or real model call — the LLM
// wiring lands in a later slice. Drafting requires a selected Human Intervention
// Case; with none the gateway returns the idle needs_case prompt. When the
// employee asks for an SMS draft on an SMS case, a draft card is attached via the
// governed toee_copilot_draft tool (best-effort: omitted if the tool fails).
import { executeTool } from "@toee/domain-adapters";
import { json, problem } from "../respond";
import { copilotContext, readJsonBody, type CopilotDeps } from "./deps";

const NEEDS_CASE_REPLY = "Select a Human Intervention Case to begin.";

export async function handleChat(
  req: Request,
  deps: CopilotDeps,
): Promise<Response> {
  const body = await readJsonBody(req);
  const message =
    typeof body?.message === "string" ? body.message : "";
  if (message.trim().length === 0) return problem(400, "message is required");

  const caseId =
    typeof body?.caseId === "string" && body.caseId.length > 0
      ? body.caseId
      : undefined;
  if (!caseId) {
    return json({ state: "needs_case", reply: NEEDS_CASE_REPLY });
  }

  const found = deps.store.getCase(caseId);
  if (!found) return problem(404, "case not found");

  const reply = `Reviewing ${found.identitySummary} — contact reason: ${found.contactReason}. How can I help with this case?`;

  // Deterministic intent heuristic — never a real model. Only SMS cases can get
  // an SMS draft card (ADR-0081 active-case drafting).
  const wantsDraft = /draft|sms/i.test(message);
  if (wantsDraft && found.channel === "sms") {
    const result = await executeTool({
      tool: "toee_copilot_draft",
      action: "draft_sms",
      params: { caseId, prompt: message },
      context: copilotContext(deps),
      driver: deps.driver,
    });
    if (result.ok) {
      const data = result.data as { draft?: unknown };
      const draftBody = typeof data.draft === "string" ? data.draft : "";
      return json({
        state: "ready",
        reply,
        draftCard: { channel: "sms", body: draftBody },
      });
    }
  }

  return json({ state: "ready", reply });
}
