// Typed, thin wrappers over the Simulator BFF routes (0.0.3 S02/S03, FR-8/9).
// Mirrors copilot-client.ts's pattern -- same http helpers, same same-origin
// cookie-riding fetch -- kept in its own file since the simulator ingress/thread
// contract is deliberately separate from the real Copilot BFF (§7 seam 1: no
// bypass chat, the simulator only ever talks to the real gateway webhook).
import { getJson, sendJson } from "./http";
import type { ThreadMessage } from "../gateway/types";

const BASE = "/api/copilot/simulator";

export type SimulatorSendResponse = {
  conversationId: string;
  eventId: string;
  accepted: boolean;
};

export type SimulatorThreadResponse = {
  caseId: string | null;
  messages: ThreadMessage[];
};

export function sendSimulatorMessage(input: {
  fromPhone: string;
  body: string;
  conversationId?: string;
}): Promise<SimulatorSendResponse> {
  return sendJson("POST", `${BASE}/messages`, input);
}

export function getSimulatorThread(fromPhone: string): Promise<SimulatorThreadResponse> {
  return getJson(`${BASE}/thread?fromPhone=${encodeURIComponent(fromPhone)}`);
}

// S18/FR-11: the email sibling of sendSimulatorMessage/getSimulatorThread --
// composes {from, subject, body} to the email ingress route (item 1) and
// reads the reply back keyed by fromAddress (get_thread_by_email, S18).
export function sendSimulatorEmail(input: {
  from: string;
  subject: string;
  body: string;
  conversationId?: string;
}): Promise<SimulatorSendResponse> {
  return sendJson("POST", `${BASE}/email`, input);
}

export function getSimulatorEmailThread(fromAddress: string): Promise<SimulatorThreadResponse> {
  return getJson(`${BASE}/thread?fromAddress=${encodeURIComponent(fromAddress)}`);
}

export type SimulatorLinkIdentityResponse = {
  linked: boolean;
  channel: string;
  channelIdentity: string;
  shopifyCustomerId: string;
};

// S05 (FR-13): simulates the ingress event that links the current channel
// identity (the simulator's "From phone") to a verified customer, through the
// production Identity Graph linking path (toee_identity_lookup.link_identity).
export function linkSimulatorIdentity(input: {
  channelIdentity: string;
  shopifyCustomerId: string;
  companyName?: string;
}): Promise<SimulatorLinkIdentityResponse> {
  return sendJson("POST", `${BASE}/link-identity`, input);
}
