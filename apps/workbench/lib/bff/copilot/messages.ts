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

interface SentTextlineMessage {
  messageId: string;
  conversationId: string;
  body: string;
  mediaUrl?: string;
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
