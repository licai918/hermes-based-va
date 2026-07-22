// Governed SMS send (ADR-0083, ADR-0141 / #42). Phase-1 customer-facing write:
// an employee sends an SMS reply inside an active SMS Session on a case they hold.
// Strict precondition order — 400 empty body, 404 missing case, 403 ineligible —
// then a governed `toee_case_manage.send_sms_message` over tools:dispatch, so the
// vendor capture, the message_turn mirror, and the sms_send audit land server-side
// in one transaction. ADR-0035 keeps `toee_sms_reply` off the copilot allowlist
// (agent no-send); this composite action is the employee-confirmed write seam.
// On tool failure nothing is fabricated.
import { json, problem } from "../respond";
import { readJsonBody, readNonEmptyString } from "./deps";
import { dispatchGetCaseData } from "./cases";
import type { WorkbenchSession } from "../../auth/session";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { mapWorkbenchCase } from "../../gateway/hermes-map";

interface SentSmsMessage {
  messageId: string;
  conversationId: string;
  body: string;
  mediaUrl?: string;
}

function mapSentSmsMessage(
  raw: Record<string, unknown>,
  fallbackBody: string,
): SentSmsMessage {
  const message: SentSmsMessage = {
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

export async function handleSmsSendViaApi(
  req: Request,
  client: HermesApiClient,
  session: WorkbenchSession,
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
    // ADR-0083 preconditions: an SMS case, with an active SMS Session, held by the
    // acting account. All three must hold or the send is refused before dispatch.
    const eligible =
      mapped.channel === "sms" &&
      mapped.smsSessionActive === true &&
      mapped.assigneeAccountId === session.accountId;
    if (!eligible) return problem(403, "case not eligible for SMS send");

    const mediaUrl = readNonEmptyString(raw, "mediaUrl") ?? undefined;
    const result = (await client.dispatchWrite(
      "toee_case_manage",
      "send_sms_message",
      {
        case_id: caseId,
        body: text,
        ...(mediaUrl ? { media_url: mediaUrl } : {}),
      },
    )) as { message?: Record<string, unknown> };
    const msg = result?.message ?? {};
    return json({ message: mapSentSmsMessage(msg, text) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
