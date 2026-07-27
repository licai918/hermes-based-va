// Copilot Gateway conversation (ADR-0081, ADR-0147 Slice 4, #39). The reply is a
// genuine unbound `internal_copilot` agent turn over `POST /v1/agent:turn` (the LLM
// seam, channel `chat`). Drafting requires a selected Human Intervention Case; with
// none the gateway returns the idle needs_case prompt. When the employee asks for an
// SMS draft on an SMS case, the reply is also attached as a draft card.
//
// 0.0.4 S09 deleted the deterministic in-memory `handleChat` stub: the agent-turn
// API is the only chat path. A local run needs the dispatch server to resolve a
// model (OPENROUTER_API_KEY, or its own keyless stub); automated tests drive the
// turn through the `scripted_completions` seam server-side, or mock HermesAgentClient
// here.
import { json, problem } from "../respond";
import { readJsonBody } from "./deps";
import type { HermesAgentClient } from "../../gateway/hermes-agent-client";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";

const NEEDS_CASE_REPLY = "Select a Human Intervention Case to begin.";

// Chat is SINGLE-SHOT — one `message` + a selected case → one reply, no conversation
// history — so this mirrors `handleDraftViaApi`, not a multi-turn protocol. It writes
// NO audit: the `chat` turn-mode records none server-side either, since a
// conversational reply is not a draft_generated event.
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
  // No case selected → the idle prompt, with no network. Checked after the
  // empty-message 400, same order.
  if (!caseId) return json({ state: "needs_case", reply: NEEDS_CASE_REPLY });

  try {
    // 404 + draftCard gating in one read: a chat turn needs a real case, and the SMS
    // card only attaches on an SMS case. A null read is a legitimate empty read
    // (ADR-0020) → 404; the `channel` decides the card.
    const found = (await client.dispatch("toee_workbench_read", "get_case", {
      case_id: caseId,
    })) as { case?: { channel?: unknown } | null };
    if (!found || found.case == null) return problem(404, "case not found");

    // The reply is the unbound internal_copilot chat turn's final_response (Fork E1),
    // never a send (the profile has no send tool, ADR-0035/0067).
    const reply = await agent.chatReply({ caseId, message });

    // Only an SMS case, and only when the message reads like a draft request, gets an
    // SMS draft card. The chat reply IS the suggested reply text, surfaced into the
    // editable card (no separate, audit-writing draft turn).
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
