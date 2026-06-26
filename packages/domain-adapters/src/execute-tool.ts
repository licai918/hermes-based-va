import { isToolAction, isToolName, type ToolName } from "@toee/shared";
import { ToolDriverError, type ToolErrorClass } from "./errors";
import type { IntegrationDriver } from "./driver";
import {
  allowAllGate,
  type ToolExecutionContext,
  type ToolGate,
} from "./tool-gate";

// Customer-facing replies must never expose raw driver, OAuth, or vendor
// errors (ADR-0136). Internal/log messages stay on the audit record only.
const TOOL_UNAVAILABLE_MESSAGE =
  "The requested system is temporarily unavailable.";

export interface ToolRequest {
  tool: ToolName;
  action: string;
  params: Record<string, unknown>;
}

// A driver executes a validated, gate-approved request against an integration
// backend. Concrete mock/composio/rest drivers land in later slices.
export interface ToolDriver {
  readonly kind: IntegrationDriver;
  execute(request: ToolRequest, context: ToolExecutionContext): Promise<unknown>;
}

// Audit metadata emitted for every tool execution attempt (ADR-0136). The same
// fields back Copilot Workbench review and structured ops logs.
export interface ToolAuditRecord {
  tool: string;
  action: string;
  driver: IntegrationDriver;
  outcome: "ok" | "unavailable";
  errorClass?: ToolErrorClass;
  userId?: string;
  connectedAccountId?: string;
}

export type AuditSink = (record: ToolAuditRecord) => void;

export type ToolResult =
  | { ok: true; data: unknown; audit: ToolAuditRecord }
  | {
      ok: false;
      errorClass: ToolErrorClass;
      message: string;
      audit: ToolAuditRecord;
    };

export interface ExecuteToolOptions {
  tool: string;
  action: string;
  params?: Record<string, unknown>;
  context: ToolExecutionContext;
  driver: ToolDriver;
  gate?: ToolGate;
  audit?: AuditSink;
}

// Validates the tool/action against the v1 catalog, runs the Tool Gate before
// any driver call, invokes the driver, and emits audit metadata. Any unknown
// tool/action, gate denial, or driver failure becomes a governed failure rather
// than a thrown exception or fabricated result (ADR-0020).
export async function executeTool(
  options: ExecuteToolOptions,
): Promise<ToolResult> {
  const { tool, action, context, driver } = options;
  const gate = options.gate ?? allowAllGate;
  const params = options.params ?? {};
  const emit = options.audit ?? (() => {});

  const fail = (
    errorClass: ToolErrorClass,
    message: string,
  ): ToolResult => {
    const audit: ToolAuditRecord = {
      tool,
      action,
      driver: driver.kind,
      outcome: "unavailable",
      errorClass,
      userId: context.userId,
      connectedAccountId: context.connectedAccountId,
    };
    emit(audit);
    return { ok: false, errorClass, message, audit };
  };

  if (!isToolName(tool)) {
    return fail("unknown_tool", `Unknown tool "${tool}".`);
  }

  if (!isToolAction(tool, action)) {
    return fail(
      "unknown_action",
      `Unknown action "${action}" for tool "${tool}".`,
    );
  }

  const decision = gate({ tool, action }, context);
  if (!decision.allow) {
    return fail(decision.errorClass, decision.message);
  }

  try {
    const data = await driver.execute({ tool, action, params }, context);
    const audit: ToolAuditRecord = {
      tool,
      action,
      driver: driver.kind,
      outcome: "ok",
      userId: context.userId,
      connectedAccountId: context.connectedAccountId,
    };
    emit(audit);
    return { ok: true, data, audit };
  } catch (error) {
    return fail(classifyDriverError(error), TOOL_UNAVAILABLE_MESSAGE);
  }
}

function classifyDriverError(error: unknown): ToolErrorClass {
  if (error instanceof ToolDriverError) {
    return error.errorClass;
  }
  return "unexpected_error";
}
