import type { ToolName } from "@toee/shared";
import { ToolDriverError } from "../errors";
import type { ToolDriver, ToolRequest } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";

// A mock handler produces a deterministic response for one tool action. It may
// throw ToolDriverError to exercise governed failure paths. Tool/action
// validation already happened in executeTool, so handlers only see catalog-valid
// requests.
export type MockActionHandler = (
  params: Record<string, unknown>,
  context: ToolExecutionContext,
) => unknown | Promise<unknown>;

// Handlers for one tool, keyed by v1 action.
export type MockToolHandlers = Partial<Record<string, MockActionHandler>>;

// A fragment of the mock registry covering one or more tools. Each domain mock
// module exports such a fragment; they merge into the full driver because each
// domain owns distinct tool names.
export type MockHandlerRegistry = Partial<Record<ToolName, MockToolHandlers>>;

// Builds a `mock` ToolDriver that routes each request to its registered handler.
// A catalog-valid action with no registered handler is a `configuration_missing`
// governed failure rather than a silent success.
export function createMockDriver(registry: MockHandlerRegistry): ToolDriver {
  return {
    kind: "mock",
    async execute(
      request: ToolRequest,
      context: ToolExecutionContext,
    ): Promise<unknown> {
      const handler = registry[request.tool]?.[request.action];
      if (handler === undefined) {
        throw new ToolDriverError(
          "configuration_missing",
          `No mock handler registered for ${request.tool}.${request.action}.`,
        );
      }
      return handler(request.params, context);
    },
  };
}
