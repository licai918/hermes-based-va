// Copilot Gateway conversation (ADR-0081). Two paths: `handleChat` is the in-memory
// fallback — a fully deterministic acknowledgement with no network or real model
// call — and `handleChatViaApi` (ADR-0147 Slice 4, #39) runs the reply as a genuine
// unbound internal_copilot agent turn over the agent-turn (LLM) API. Both share the
// same surface: drafting requires a selected Human Intervention Case; with none the
// gateway returns the idle needs_case prompt. When the employee asks for an SMS draft
// on an SMS case, a draft card is attached (the in-memory path via the governed
// toee_copilot_draft tool, the API path via the chat reply itself — best-effort).
import { executeTool } from "@toee/domain-adapters";
import { json, problem } from "../respond";
import { copilotContext, readJsonBody, type CopilotDeps } from "./deps";
import type { HermesAgentClient } from "../../gateway/hermes-agent-client";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";

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

// Per-profile API variant of chat (ADR-0147 Slice 4, closes #39): the reply is a
// genuine unbound `internal_copilot` agent turn over `POST /v1/agent:turn` (the LLM
// seam, channel `chat`) instead of the deterministic stub above. Chat is SINGLE-SHOT
// — the in-memory handleChat contract is one `message` + a selected case → one reply,
// with no conversation history (it ignores history entirely) — so this mirrors
// `handleDraftViaApi`, not a multi-turn protocol. It preserves the stub's surface
// byte-for-byte: 400 empty message, the needs_case idle state (200, no network), 404
// unknown case, and the `{ state, reply, draftCard? }` body with the same
// `/draft|sms/i` + SMS-channel draftCard gating. It writes NO audit (store-path
// parity: handleChat audits nothing, and the `chat` turn-mode records none
// server-side either — a conversational reply is not a draft_generated event). The
// route selects this only when HERMES_COPILOT_API_URL/TOKEN are set, else falls back
// to handleChat.
export async function handleChatViaApi(
  req: Request,
  agent: HermesAgentClient,
  client: HermesApiClient,
): Promise<Response> {
  const body = await readJsonBody(req);
  const message = typeof body?.message === "string" ? body.message : "";
  if (message.trim().length === 0) return problem(400, "message is required");

  const caseId =
    typeof body?.caseId === "string" && body.caseId.length > 0
      ? body.caseId
      : undefined;
  // No case selected → the idle prompt, with no network (mirrors handleChat, which
  // never touches the store here). Checked after the empty-message 400, same order.
  if (!caseId) return json({ state: "needs_case", reply: NEEDS_CASE_REPLY });

  try {
    // 404 parity + draftCard gating in one read: a chat turn needs a real case, and
    // the SMS card only attaches on an SMS case. A null read is a legitimate empty
    // read (ADR-0020) → 404, like handleChat's getCase miss; the `channel` decides
    // the card (absent in mock mode → no card, a graceful degrade matching the stub's
    // best-effort attach).
    const found = (await client.dispatch("toee_workbench_read", "get_case", {
      case_id: caseId,
    })) as { case?: { channel?: unknown } | null };
    if (!found || found.case == null) return problem(404, "case not found");

    // The reply is the unbound internal_copilot chat turn's final_response (Fork E1),
    // never a send (the profile has no send tool, ADR-0035/0067).
    const reply = await agent.chatReply({ caseId, message });

    // Same heuristic + channel gate as handleChat: only an SMS case, and only when the
    // message reads like a draft request, gets an SMS draft card. The chat reply IS the
    // suggested reply text, surfaced into the editable card (no separate, audit-writing
    // draft turn — that would diverge from handleChat, which audits nothing).
    const wantsDraft = /draft|sms/i.test(message);
    if (wantsDraft && found.case.channel === "sms") {
      return json({
        state: "ready",
        reply,
        draftCard: { channel: "sms", body: reply },
      });
    }
    return json({ state: "ready", reply });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
