// Copilot Draft Action handler (ADR-0067, ADR-0081). Generates an SMS/email/
// internal-note draft for a selected case via the governed toee_copilot_draft
// tool. Drafting requires a valid selected case (no drafting without a case);
// the result is a suggestion only — sending is a separate governed action.
import { executeTool } from "@toee/domain-adapters";
import { json, problem } from "../respond";
import {
  appendAudit,
  copilotContext,
  readJsonBody,
  readNonEmptyString,
  type CopilotDeps,
} from "./deps";

export type DraftAction = "draft_sms" | "draft_email" | "draft_internal_note";

export async function handleDraft(
  req: Request,
  deps: CopilotDeps,
  action: DraftAction,
): Promise<Response> {
  const body = await readJsonBody(req);
  const caseId = readNonEmptyString(body, "caseId");
  if (!caseId) return problem(400, "caseId is required");
  if (!deps.store.getCase(caseId)) return problem(404, "case not found");

  const prompt = readNonEmptyString(body, "prompt") ?? undefined;
  const result = await executeTool({
    tool: "toee_copilot_draft",
    action,
    params: { caseId, prompt },
    context: copilotContext(deps),
    driver: deps.driver,
  });
  if (!result.ok) return problem(502, result.message);

  appendAudit(deps, "draft_generated", { caseId, detail: action });
  return json({ draft: result.data });
}
