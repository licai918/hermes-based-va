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
import type {
  DraftChannel,
  HermesAgentClient,
} from "../../gateway/hermes-agent-client";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";

export type DraftAction = "draft_sms" | "draft_email" | "draft_internal_note";

const CHANNEL_BY_ACTION: Record<DraftAction, DraftChannel> = {
  draft_sms: "sms",
  draft_email: "email",
  draft_internal_note: "internal_note",
};

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

// Per-profile API variant of the draft (ADR-0147 Slice 1): the draft is generated
// by a genuine unbound internal_copilot agent turn over `POST /v1/agent:turn` (the
// LLM seam) instead of the in-process mock. It preserves the store path's surface
// byte-for-byte — 400 missing caseId, 404 unknown case, the `draft_generated` audit
// (detail = action), the `{ draft: { channel, draft } }` body — and maps a governed
// or transport failure through the ADR-0104 per-class status (no audit on failure).
// The 404 pre-read goes to the deterministic dispatch (the datastore is the source
// of truth in API mode), mirroring the case-write cutover; the audit stays on the
// BFF (ADR-0147 sub-fork). The route selects this only when HERMES_COPILOT_API_URL/
// TOKEN are set, else it falls back to the in-memory `handleDraft`.
export async function handleDraftViaApi(
  req: Request,
  agent: HermesAgentClient,
  client: HermesApiClient,
  deps: CopilotDeps,
  action: DraftAction,
): Promise<Response> {
  const body = await readJsonBody(req);
  const caseId = readNonEmptyString(body, "caseId");
  if (!caseId) return problem(400, "caseId is required");
  const prompt = readNonEmptyString(body, "prompt") ?? undefined;
  try {
    // 404 parity: a draft needs a real case. A null read is a legitimate empty
    // read (ADR-0020) -> 404, like the store path's `getCase` miss.
    const found = (await client.dispatch("toee_workbench_read", "get_case", {
      case_id: caseId,
    })) as { case?: unknown };
    if (!found || found.case == null) return problem(404, "case not found");

    const data = await agent.generateDraft({
      channel: CHANNEL_BY_ACTION[action],
      caseId,
      prompt,
    });
    appendAudit(deps, "draft_generated", { caseId, detail: action });
    // Store-path parity: the in-process handleDraft returns `{ draft: <tool data> }`
    // verbatim. Here the agent's per-channel envelope IS that data, so we pass it
    // through minus `provenance` (governance metadata the textarea never binds).
    // This covers all three channel shapes — sms/email `{channel,...}`, email's
    // `subject`, note's `{kind,...}` — without per-channel branching, exactly
    // mirroring the mock's per-channel tool output.
    const { provenance: _provenance, ...draft } = data;
    return json({ draft });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
