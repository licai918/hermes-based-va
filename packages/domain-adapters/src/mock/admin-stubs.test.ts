import { describe, it, expect } from "vitest";
import { HERMES_PROFILES, TOOL_CATALOG, type ToolName } from "@toee/shared";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";
import { createMockDriver } from "./mock-driver";
import { adminStubMockHandlers } from "./admin-stubs";

const copilotContext: ToolExecutionContext = {
  profile: HERMES_PROFILES.internalCopilot,
};
const adminContext: ToolExecutionContext = {
  profile: HERMES_PROFILES.supervisorAdmin,
};

const driver = createMockDriver(adminStubMockHandlers);

function call(
  tool: string,
  action: string,
  context: ToolExecutionContext,
  params: Record<string, unknown> = {},
) {
  return executeTool({ tool, action, params, context, driver });
}

const STUB_TOOLS = [
  "toee_workbench_read",
  "toee_case_manage",
  "toee_copilot_draft",
  "toee_knowledge_ops",
  "toee_eval_review",
  "toee_workbench_admin",
] as const satisfies readonly ToolName[];

describe("admin/copilot stubs are callable for every v1 action", () => {
  for (const tool of STUB_TOOLS) {
    for (const action of TOOL_CATALOG[tool]) {
      it(`${tool}.${action} returns a deterministic stub object`, async () => {
        const params = {
          caseId: "c1",
          assigneeId: "u1",
          slot: "s1",
          runId: "r1",
          accountId: "a1",
        };

        const first = await call(tool, action, copilotContext, params);
        const second = await call(tool, action, copilotContext, params);

        expect(first.ok).toBe(true);
        expect(second.ok).toBe(true);
        if (first.ok && second.ok) {
          expect(typeof first.data).toBe("object");
          expect(first.data).not.toBeNull();
          expect(first.data).toEqual(second.data);
        }
      });
    }
  }
});

describe("admin/copilot stubs return their documented minimal shapes", () => {
  it("toee_workbench_read.get_case echoes the case id with an open status", async () => {
    const result = await call("toee_workbench_read", "get_case", copilotContext, {
      caseId: "case_1",
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({ caseId: "case_1", status: "open" });
    }
  });

  it("toee_workbench_read.list_cases returns an empty case list", async () => {
    const result = await call(
      "toee_workbench_read",
      "list_cases",
      copilotContext,
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ cases: [] });
    }
  });

  it("toee_copilot_draft.draft_sms returns a draft string", async () => {
    const result = await call("toee_copilot_draft", "draft_sms", copilotContext);
    expect(result.ok).toBe(true);
    if (result.ok) {
      const data = result.data as { draft: unknown };
      expect(typeof data.draft).toBe("string");
    }
  });

  it("toee_workbench_admin.list_accounts returns an empty accounts list", async () => {
    const result = await call(
      "toee_workbench_admin",
      "list_accounts",
      adminContext,
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ accounts: [] });
    }
  });
});
