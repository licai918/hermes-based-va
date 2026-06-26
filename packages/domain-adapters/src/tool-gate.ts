import type {
  HermesProfileId,
  SessionIdentitySnapshot,
  ToolName,
} from "@toee/shared";
import type { ToolErrorClass } from "./errors";

// Runtime context a Tool Gate evaluates against: the active Hermes Profile, the
// session identity snapshot, and the connected-account identifiers used for
// audit (ADR-0033, ADR-0136).
export interface ToolExecutionContext {
  profile: HermesProfileId;
  identity?: SessionIdentitySnapshot;
  userId?: string;
  connectedAccountId?: string;
}

export type ToolGateDecision =
  | { allow: true }
  | { allow: false; errorClass: ToolErrorClass; message: string };

// A Tool Gate runs inside adapter dispatch before the driver is invoked. It is
// not a separate Hermes core module (ADR-0033); it is a hook point Toee Tire
// policy checks plug into.
export type ToolGate = (
  request: { tool: ToolName; action: string },
  context: ToolExecutionContext,
) => ToolGateDecision;

// Default gate used when no policy checks are wired (e.g. mock-first scaffold).
export const allowAllGate: ToolGate = () => ({ allow: true });
