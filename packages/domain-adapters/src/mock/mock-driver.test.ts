import { describe, it, expect } from "vitest";
import { HERMES_PROFILES } from "@toee/shared";
import { createMockDriver } from "./mock-driver";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";

const context: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
};

describe("createMockDriver", () => {
  it("reports the mock driver kind", () => {
    const driver = createMockDriver({});
    expect(driver.kind).toBe("mock");
  });

  it("routes a tool and action to its registered handler", async () => {
    const driver = createMockDriver({
      toee_sms_reply: {
        send_message: (params) => ({ echoed: params.body }),
      },
    });

    const result = await executeTool({
      tool: "toee_sms_reply",
      action: "send_message",
      params: { body: "hi" },
      context,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ echoed: "hi" });
    }
  });

  it("returns a governed failure when no mock handler is registered", async () => {
    const driver = createMockDriver({});

    const result = await executeTool({
      tool: "toee_sms_reply",
      action: "send_message",
      context,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errorClass).toBe("configuration_missing");
    }
  });
});
