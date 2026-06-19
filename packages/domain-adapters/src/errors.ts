// Governed failure classification for Domain Adapter Tool execution.
// Dispatch-level classes (`unknown_tool`, `unknown_action`, `policy_blocked`)
// extend the runtime driver classes from ADR-0136. `unexpected_error` covers
// driver throws that are not classified by the driver itself.
export type ToolErrorClass =
  | "unknown_tool"
  | "unknown_action"
  | "policy_blocked"
  | "auth_expired"
  | "vendor_timeout"
  | "composio_api_error"
  | "configuration_missing"
  | "unexpected_error";

// Drivers throw this to signal a governed Tool Unavailable Response with a
// specific error class (ADR-0020, ADR-0136). The raw message is for logs only
// and must never reach customer-facing replies.
export class ToolDriverError extends Error {
  readonly errorClass: ToolErrorClass;

  constructor(errorClass: ToolErrorClass, message: string) {
    super(message);
    this.name = "ToolDriverError";
    this.errorClass = errorClass;
  }
}
