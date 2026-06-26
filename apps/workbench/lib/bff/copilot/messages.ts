// Governed Textline send (ADR-0083). Phase-1 customer-facing write: an employee
// sends an SMS reply inside an active SMS Session on a case they hold. Strict
// precondition order — 400 empty body, 404 missing case, 403 ineligible — then a
// governed toee_textline_reply.send_message. The captured outbound message is
// mirrored into the Case Thread Context and the Workbench Audit Log; on tool
// failure nothing is fabricated.
import { executeTool } from "@toee/domain-adapters";
import { json, problem } from "../respond";
import {
  appendAudit,
  copilotContext,
  readJsonBody,
  readNonEmptyString,
  type CopilotDeps,
} from "./deps";
import { dispatchGetCaseData } from "./cases";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { mapWorkbenchCase } from "../../gateway/hermes-map";

interface SentTextlineMessage {
  messageId: string;
  conversationId: string;
  body: string;
  mediaUrl?: string;
}

function mapSentTextlineMessage(
  raw: Record<string, unknown>,
  fallbackBody: string,
): SentTextlineMessage {
  const message: SentTextlineMessage = {
    messageId: String(raw.message_id ?? raw.messageId ?? ""),
    conversationId: String(raw.conversation_id ?? raw.conversationId ?? ""),
    body: typeof raw.body === "string" ? raw.body : fallbackBody,
  };
  const media = raw.media_url ?? raw.mediaUrl;
  if (typeof media === "string" && media.length > 0) {
    message.mediaUrl = media;
  }
  return message;
}

export async function handleTextlineSend(
  req: Request,
  deps: CopilotDeps,
): Promise<Response> {
  const raw = await readJsonBody(req);
  const text = readNonEmptyString(raw, "body");
  if (!text) return problem(400, "body is required");

  const caseId = readNonEmptyString(raw, "caseId");
  const found = caseId ? deps.store.getCase(caseId) : undefined;
  if (!caseId || !found) return problem(404, "case not found");

  const eligible =
    found.channel === "sms" &&
    found.smsSessionActive === true &&
    found.assigneeAccountId === deps.session.accountId;
  if (!eligible) return problem(403, "case not eligible for Textline send");

  const mediaUrl = readNonEmptyString(raw, "mediaUrl") ?? undefined;
  const result = await executeTool({
    tool: "toee_textline_reply",
    action: "send_message",
    params: { conversationId: found.threadId, body: text, mediaUrl },
    context: copilotContext(deps),
    driver: deps.driver,
  });
  if (!result.ok) return problem(502, result.message);

  const sent = result.data as SentTextlineMessage;
  deps.store.appendThreadMessage(caseId, {
    messageId: sent.messageId,
    threadId: found.threadId,
    at: deps.now,
    author: "workbench",
    channel: "sms",
    body: text,
    autoHandled: false,
    activeCaseSegment: true,
  });
  appendAudit(deps, "textline_send", { caseId, detail: text });
  return json({ message: result.data });
}

// Per-profile API variant (ADR-0141 / #42): the governed send runs as
// `toee_case_manage.send_textline_message` over tools:dispatch so the vendor
// capture, message_turn mirror, and textline_send audit land server-side in one
// transaction. ADR-0035 keeps `tooe_textline_reply` off the copilot allowlist
// (agent no-send); this composite action is the employee-confirmed write seam.
// Pre-read get_case for 404/403 parity with the store path; no in-memory thread
// or audit double-write when the API is configured.
export async function handleTextlineSendViaApi(
  req: Request,
  client: HermesApiClient,
  deps: CopilotDeps,
): Promise<Response> {
  const raw = await readJsonBody(req);
  const text = readNonEmptyString(raw, "body");
  if (!text) return problem(400, "body is required");

  const caseId = readNonEmptyString(raw, "caseId");
  if (!caseId) return problem(404, "case not found");

  try {
    const found = await dispatchGetCaseData(client, caseId);
    if (found == null) return problem(404, "case not found");
    const mapped = mapWorkbenchCase(found);
    const eligible =
      mapped.channel === "sms" &&
      mapped.smsSessionActive === true &&
      mapped.assigneeAccountId === deps.session.accountId;
    if (!eligible) return problem(403, "case not eligible for Textline send");

    const mediaUrl = readNonEmptyString(raw, "mediaUrl") ?? undefined;
    const result = (await client.dispatchWrite(
      "toee_case_manage",
      "send_textline_message",
      {
        case_id: caseId,
        body: text,
        ...(mediaUrl ? { media_url: mediaUrl } : {}),
      },
    )) as { message?: Record<string, unknown> };
    const msg = result?.message ?? {};
    return json({ message: mapSentTextlineMessage(msg, text) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
