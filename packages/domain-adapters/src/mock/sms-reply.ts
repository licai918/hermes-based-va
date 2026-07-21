// Mock driver fragment for `toee_sms_reply` (ADR-0066). `send_message`
// captures the outbound SMS into an in-memory outbox and returns a
// deterministic record. It performs NO network/external call — the capture is
// the side effect Launch Eval and the Copilot Workbench audit inspect. Optional
// `media_url` supports Product Media Reply.
import type { MockHandlerRegistry } from "./mock-driver";

export interface OutboundSmsMessage {
  messageId: string;
  conversationId: string;
  body: string;
  mediaUrl?: string;
}

export interface SmsReplyMockData {
  // Captured outbound messages, in send order. The eval fixture loader inspects
  // this to assert what Hermes sent in the current SMS Session.
  outbox: OutboundSmsMessage[];
  // Prefix for the deterministic messageId.
  messageIdPrefix: string;
}

// Fresh, isolated mock data — preferred for tests/scenarios so captured
// messages never leak across runs.
export function createSmsReplyMockData(): SmsReplyMockData {
  return { outbox: [], messageIdPrefix: "msg" };
}

export const smsReplyBaselineData: SmsReplyMockData = createSmsReplyMockData();

function readString(
  params: Record<string, unknown>,
  ...keys: string[]
): string | undefined {
  for (const key of keys) {
    const value = params[key];
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }
  return undefined;
}

// Deterministic 32-bit FNV-1a hash rendered as an 8-char hex suffix. No clock or
// randomness, so an identical send always yields the same messageId.
function deterministicId(
  prefix: string,
  parts: Array<string | undefined>,
): string {
  const input = parts.map((part) => part ?? "").join("|");
  let hash = 0x811c9dc5;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `${prefix}_${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function sendMessage(
  data: SmsReplyMockData,
  params: Record<string, unknown>,
): OutboundSmsMessage {
  const conversationId =
    readString(params, "conversationId", "conversation_id") ?? "";
  const body = readString(params, "body") ?? "";
  const mediaUrl = readString(params, "mediaUrl", "media_url");

  const message: OutboundSmsMessage = {
    messageId: deterministicId(data.messageIdPrefix, [
      conversationId,
      body,
      mediaUrl,
    ]),
    conversationId,
    body,
  };
  if (mediaUrl !== undefined) {
    message.mediaUrl = mediaUrl;
  }

  // Capture only — never call the SMS provider or any external API.
  data.outbox.push(message);
  return message;
}

export function createSmsReplyMockHandlers(
  data: SmsReplyMockData = smsReplyBaselineData,
): MockHandlerRegistry {
  return {
    toee_sms_reply: {
      send_message: (params) => sendMessage(data, params),
    },
  };
}

export const smsReplyMockHandlers: MockHandlerRegistry =
  createSmsReplyMockHandlers();
