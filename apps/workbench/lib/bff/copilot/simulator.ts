// Conversation Simulator ingress + reply read-back (FR-9, 0.0.3 S02, PRD §7 seam
// 1: "no bypass chat"). Unlike every other BFF route, ingress does NOT call
// tools:dispatch -- it composes the flat-JSON Textline webhook body Textline's
// legacy shape uses (id/conversation_id/from/body/received_at/type), signs it
// with the legacy HMAC-SHA256 (hermes/toee_hermes/gateway/verify.py's non-TGP
// branch), and POSTs it to the REAL gateway webhook, so identity match, memory,
// knowledge, and the live model all run the production path. The read-back
// route reuses the existing Case Thread Context read
// (toee_workbench_read.get_thread) via a new get_thread_by_phone action (S02):
// the simulator only ever knows the from-phone it posted, not the case_id the
// gateway's async webhook creates.
import { createHmac, randomUUID } from "node:crypto";
import { json, problem } from "../respond";
import { readJsonBody, readNonEmptyString } from "./deps";
import type { FetchLike } from "../../gateway/hermes-api-client";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { mapThreadMessage } from "../../gateway/hermes-map";

const WEBHOOK_PATH = "/webhooks/textline";
// Simulated email ingress route on the runtime gateway (0.0.3 S17/FR-18).
const EMAIL_WEBHOOK_PATH = "/webhooks/simulated-email";
// Matches scripts/simulate-textline-webhook.ps1, the proven-shape reference.
const SIMULATED_EVENT_TYPE = "message.created";
const SIMULATED_EMAIL_EVENT_TYPE = "email.received";
const LEGACY_SIGNATURE_HEADER = "X-Textline-Signature";

export interface SimulatedInboundEvent {
  id: string;
  conversation_id: string;
  from: string;
  body: string;
  received_at: string;
  type: string;
}

// Builds the legacy flat-JSON Textline webhook body (gateway_app.py
// parse_textline_fields' non-TGP branch). `eventId`/`nowIso` are injectable so
// tests get deterministic output; real callers omit them.
export function buildSimulatedInboundEvent(input: {
  fromPhone: string;
  body: string;
  conversationId: string;
  eventId?: string;
  nowIso?: string;
}): SimulatedInboundEvent {
  return {
    id: input.eventId ?? `sim-${randomUUID()}`,
    conversation_id: input.conversationId,
    from: input.fromPhone,
    body: input.body,
    received_at: input.nowIso ?? new Date().toISOString(),
    type: SIMULATED_EVENT_TYPE,
  };
}

// HMAC-SHA256 hex over the exact raw body (verify.py's legacy branch -- no
// event_type/event_time, so the TGP algorithm branch never triggers).
export function signLegacyTextlinePayload(rawBody: string, secret: string): string {
  return createHmac("sha256", secret).update(rawBody, "utf8").digest("hex");
}

export interface SimulatorIngressConfig {
  gatewayUrl: string;
  webhookSecret: string;
  fetchImpl?: FetchLike;
}

// POST /api/copilot/simulator/messages: composes + signs the simulated inbound
// SMS and posts it to the real gateway webhook (no bypass chat -- the
// production pipeline is the thing under test). The gateway's fast-ack webhook
// only ever returns 200/401/500 with no body, so `accepted` is the gateway's
// HTTP outcome; the reply itself lands asynchronously and is read back via
// handleGetSimulatorThread.
export async function handleSimulatorIngress(
  req: Request,
  config: SimulatorIngressConfig,
): Promise<Response> {
  const raw = await readJsonBody(req);
  const fromPhone = readNonEmptyString(raw, "fromPhone");
  if (!fromPhone) return problem(400, "fromPhone is required");
  const text = readNonEmptyString(raw, "body");
  if (!text) return problem(400, "body is required");
  const conversationId = readNonEmptyString(raw, "conversationId") ?? `sim-${randomUUID()}`;

  const event = buildSimulatedInboundEvent({ fromPhone, body: text, conversationId });
  const rawBody = JSON.stringify(event);
  const signature = signLegacyTextlinePayload(rawBody, config.webhookSecret);
  const fetchImpl = config.fetchImpl ?? fetch;
  const gatewayUrl = config.gatewayUrl.replace(/\/+$/, "");

  try {
    const res = await fetchImpl(`${gatewayUrl}${WEBHOOK_PATH}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        [LEGACY_SIGNATURE_HEADER]: signature,
      },
      body: rawBody,
    });

    return json({
      conversationId: event.conversation_id,
      eventId: event.id,
      accepted: res.ok,
    });
  } catch (err) {
    // fetchImpl rejects (e.g. ECONNREFUSED when the gateway is down) rather than
    // resolving with a non-OK Response -- same convention as handleGetSimulatorThread
    // below: never let a network failure reach withSession as an unstructured 500.
    return hermesErrorToProblem(err);
  }
}

export interface SimulatedInboundEmail {
  id: string;
  conversation_id: string;
  from: string;
  subject: string;
  body: string;
  received_at: string;
  type: string;
}

// Builds the simulated email webhook body the runtime's parse_simulated_email_event
// consumes (`{from, subject, body, conversation_id, id, received_at, type}`).
// `eventId`/`nowIso` are injectable for deterministic tests.
export function buildSimulatedInboundEmail(input: {
  fromAddress: string;
  subject: string;
  body: string;
  conversationId: string;
  eventId?: string;
  nowIso?: string;
}): SimulatedInboundEmail {
  return {
    id: input.eventId ?? `sim-${randomUUID()}`,
    conversation_id: input.conversationId,
    from: input.fromAddress,
    subject: input.subject,
    body: input.body,
    received_at: input.nowIso ?? new Date().toISOString(),
    type: SIMULATED_EMAIL_EVENT_TYPE,
  };
}

// POST /api/copilot/simulator/email: composes + signs a simulated inbound email
// and posts it to the runtime's simulated-email webhook (no bypass chat — the same
// production pipeline the SMS route exercises, now Email Sender Match + email turn,
// S17/FR-18). Same fast-ack contract: the gateway returns 200/401/500 with no body;
// the reply lands asynchronously and is read back via the case view (S18 adds the
// simulator channel switcher).
export async function handleSimulatorEmailIngress(
  req: Request,
  config: SimulatorIngressConfig,
): Promise<Response> {
  const raw = await readJsonBody(req);
  const fromAddress = readNonEmptyString(raw, "from");
  if (!fromAddress) return problem(400, "from is required");
  const text = readNonEmptyString(raw, "body");
  if (!text) return problem(400, "body is required");
  const subject = readNonEmptyString(raw, "subject") ?? "";
  const conversationId = readNonEmptyString(raw, "conversationId") ?? `sim-${randomUUID()}`;

  const event = buildSimulatedInboundEmail({ fromAddress, subject, body: text, conversationId });
  const rawBody = JSON.stringify(event);
  const signature = signLegacyTextlinePayload(rawBody, config.webhookSecret);
  const fetchImpl = config.fetchImpl ?? fetch;
  const gatewayUrl = config.gatewayUrl.replace(/\/+$/, "");

  try {
    const res = await fetchImpl(`${gatewayUrl}${EMAIL_WEBHOOK_PATH}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        [LEGACY_SIGNATURE_HEADER]: signature,
      },
      body: rawBody,
    });

    return json({
      conversationId: event.conversation_id,
      eventId: event.id,
      accepted: res.ok,
    });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// POST /api/copilot/simulator/link-identity (0.0.3 S05, FR-13): the owner's
// "link identity" control. Unlike the message-send route above (which composes
// a raw webhook body), this DOES go through tools:dispatch -- link_identity is
// not a chat turn, it is a governed Identity Graph write, and tools:dispatch is
// the existing "no direct DB writes" seam every other structured write already
// uses (see preferences.ts). The Hermes dispatch server denies this action
// outright unless it is booted with REPLY_SENDER=simulated (NFR-4,
// hermes-runtime/hermes_runtime/tool_dispatch_composition.py's
// _simulated_only_gate), so production is fail-closed even if this route were
// somehow reached there. dispatchWrite (not dispatch): a governed write must
// carry the acting employee (ADR-0141).
export async function handleSimulatorLinkIdentity(
  req: Request,
  client: HermesApiClient,
): Promise<Response> {
  const body = await readJsonBody(req);
  const channelIdentity = readNonEmptyString(body, "channelIdentity");
  if (!channelIdentity) return problem(400, "channelIdentity is required");
  const shopifyCustomerId = readNonEmptyString(body, "shopifyCustomerId");
  if (!shopifyCustomerId) return problem(400, "shopifyCustomerId is required");
  const channel = readNonEmptyString(body, "channel") ?? "sms";
  const companyName = readNonEmptyString(body, "companyName");

  try {
    await client.dispatchWrite("toee_identity_lookup", "link_identity", {
      channel,
      channel_identity: channelIdentity,
      shopify_customer_id: shopifyCustomerId,
      ...(companyName ? { company_name: companyName } : {}),
    });
    return json({ linked: true, channel, channelIdentity, shopifyCustomerId });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// GET /api/copilot/simulator/thread?fromPhone=...: reuses the Case Thread
// Context read (ADR-0143) via get_thread_by_phone (S02) so the response shape
// and mapping are identical to the real copilot case view -- no parallel read
// path. Newest-last, same order get_thread already returns (created_at ASC).
// `caseId` (S03/FR-12) rides along so the Simulator page can link out to the
// case's real Case Thread Context in the copilot workbench; null until the
// gateway's async webhook has created a case for this phone.
export async function handleGetSimulatorThread(
  client: HermesApiClient,
  fromPhone: string,
): Promise<Response> {
  try {
    const data = (await client.dispatch("toee_workbench_read", "get_thread_by_phone", {
      from_phone: fromPhone,
    })) as { case?: { case_id?: unknown } | null; messages?: unknown };
    const rows = Array.isArray(data?.messages) ? data.messages : [];
    const caseId =
      typeof data?.case?.case_id === "string" ? data.case.case_id : null;
    return json({ caseId, messages: rows.map(mapThreadMessage) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
