// Conversation Simulator ingress + reply read-back (FR-9, 0.0.3 S02, PRD §7 seam
// 1: "no bypass chat"). Unlike every other BFF route, ingress does NOT call
// tools:dispatch -- it composes the SimpleTexting INCOMING_MESSAGE report body the
// gateway's parse_simpletexting_fields consumes and POSTs it to the REAL gateway
// webhook with the shared URL token (SimpleTexting does not sign payloads and its
// webhook registration accepts no header, so ?token= is the auth channel --
// ADR-0153), so identity match, memory, knowledge, and the live model all run the
// production path. The read-back
// route reuses the existing Case Thread Context read
// (toee_workbench_read.get_thread) via a new get_thread_by_phone action (S02):
// the simulator only ever knows the from-phone it posted, not the case_id the
// gateway's async webhook creates.
import { randomUUID } from "node:crypto";
import { json, problem } from "../respond";
import { readJsonBody, readNonEmptyString } from "./deps";
import type { FetchLike } from "../../gateway/hermes-api-client";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { mapThreadMessage } from "../../gateway/hermes-map";

const WEBHOOK_PATH = "/webhooks/simpletexting";
// Simulated email ingress route on the runtime gateway (0.0.3 S17/FR-18).
const EMAIL_WEBHOOK_PATH = "/webhooks/simulated-email";
// Matches scripts/simulate-simpletexting-webhook.ps1, the proven-shape reference.
const SIMULATED_EVENT_TYPE = "INCOMING_MESSAGE";
const SIMULATED_EMAIL_EVENT_TYPE = "email.received";

// The gateway authenticates both ingress routes on this query param.
function webhookUrl(gatewayUrl: string, path: string, token: string): string {
  return `${gatewayUrl}${path}?token=${encodeURIComponent(token)}`;
}

export interface SimulatedInboundEvent {
  reportId: string;
  webhookId: string;
  type: string;
  values: {
    messageId: string;
    text: string;
    accountPhone: string;
    contactPhone: string;
    timestamp: string;
    category: string;
  };
}

// Builds the SimpleTexting INCOMING_MESSAGE report body (gateway_app.py
// parse_simpletexting_fields). `eventId`/`nowIso` are injectable so tests get
// deterministic output; real callers omit them.
export function buildSimulatedInboundEvent(input: {
  fromPhone: string;
  body: string;
  conversationId: string;
  eventId?: string;
  nowIso?: string;
}): SimulatedInboundEvent {
  const messageId = input.eventId ?? `sim-${randomUUID()}`;
  return {
    reportId: `rep-${messageId}`,
    webhookId: "wh-simulator",
    type: SIMULATED_EVENT_TYPE,
    values: {
      messageId,
      text: input.body,
      accountPhone: "simulator",
      // SimpleTexting has no conversation resource: the contact phone IS the
      // conversation, so the caller's conversationId is not sent separately.
      contactPhone: input.fromPhone,
      timestamp: input.nowIso ?? new Date().toISOString(),
      category: "SMS",
    },
  };
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
  const fetchImpl = config.fetchImpl ?? fetch;
  const gatewayUrl = config.gatewayUrl.replace(/\/+$/, "");

  try {
    const res = await fetchImpl(webhookUrl(gatewayUrl, WEBHOOK_PATH, config.webhookSecret), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: rawBody,
    });

    return json({
      conversationId: event.values.contactPhone,
      eventId: event.values.messageId,
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

// POST /api/copilot/simulator/email: composes a simulated inbound email
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
  const fetchImpl = config.fetchImpl ?? fetch;
  const gatewayUrl = config.gatewayUrl.replace(/\/+$/, "");

  try {
    const res = await fetchImpl(
      webhookUrl(gatewayUrl, EMAIL_WEBHOOK_PATH, config.webhookSecret),
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: rawBody,
      },
    );

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

// GET /api/copilot/simulator/thread?fromAddress=...: the email sibling of
// handleGetSimulatorThread above (S18/FR-11) -- same Case Thread Context read
// (ADR-0143), keyed by get_thread_by_email (S18) instead of get_thread_by_phone,
// since the simulator only ever knows the from-address it posted through
// handleSimulatorEmailIngress, not the case_id the gateway's async webhook
// creates.
export async function handleGetSimulatorEmailThread(
  client: HermesApiClient,
  fromAddress: string,
): Promise<Response> {
  try {
    const data = (await client.dispatch("toee_workbench_read", "get_thread_by_email", {
      from_address: fromAddress,
    })) as { case?: { case_id?: unknown } | null; messages?: unknown };
    const rows = Array.isArray(data?.messages) ? data.messages : [];
    const caseId =
      typeof data?.case?.case_id === "string" ? data.case.case_id : null;
    return json({ caseId, messages: rows.map(mapThreadMessage) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
