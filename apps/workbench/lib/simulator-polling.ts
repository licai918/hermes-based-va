// Pure polling logic for the Simulator page (0.0.3 S03): the agent's reply
// arrives asynchronously (webhook ack -> background turn -> mirrored to
// message_turn), so after an accepted send the UI polls GET .../thread and
// stops as soon as a new Hermes-authored turn shows up. Extracted so the
// "did a reply land" check is unit-testable without mounting the component.
import type { ThreadMessage } from "./gateway/types";

export function countOutbound(messages: ThreadMessage[]): number {
  return messages.filter((m) => m.author === "hermes").length;
}

export function hasNewOutboundReply(
  before: ThreadMessage[],
  after: ThreadMessage[],
): boolean {
  return countOutbound(after) > countOutbound(before);
}
