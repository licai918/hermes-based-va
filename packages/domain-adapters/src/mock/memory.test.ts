import { describe, it, expect } from "vitest";
import { HERMES_PROFILES, type SessionIdentitySnapshot } from "@toee/shared";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";
import { createMockDriver } from "./mock-driver";
import { createMemoryMockHandlers, memoryMockHandlers } from "./memory";

const verifiedIdentity: SessionIdentitySnapshot = {
  outcome: "verified_customer",
  shopifyCustomerId: "gid://shopify/Customer/1001",
  resolvedAt: "2026-01-01T00:00:00.000Z",
};

const context: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
  identity: verifiedIdentity,
};

describe("toee_customer_memory mock — scenario 24 explicit upsert", () => {
  it("records an explicit preference and get_preferences reflects it", async () => {
    const driver = createMockDriver(createMemoryMockHandlers());

    const upsert = await executeTool({
      tool: "toee_customer_memory",
      action: "upsert_preference",
      params: {
        key: "contact_time_preference",
        value: "after 2pm Eastern",
        source: "explicit_customer_statement",
      },
      context,
      driver,
    });

    expect(upsert.ok).toBe(true);
    if (upsert.ok) {
      expect(upsert.data).toMatchObject({
        slot: "contact_time_preference",
        value: "after 2pm Eastern",
        source: "explicit_customer_statement",
        stored: true,
      });
    }

    const read = await executeTool({
      tool: "toee_customer_memory",
      action: "get_preferences",
      params: {},
      context,
      driver,
    });

    expect(read.ok).toBe(true);
    if (read.ok) {
      expect(read.data).toMatchObject({
        preferences: { contact_time_preference: "after 2pm Eastern" },
      });
    }
  });
});

describe("toee_customer_memory mock — scenario 25 honor injected preference", () => {
  it("returns injected baseline preferences with no prior write", async () => {
    const driver = createMockDriver(
      createMemoryMockHandlers({
        preferences: { contact_time_preference: "after 2pm Eastern" },
      }),
    );

    const read = await executeTool({
      tool: "toee_customer_memory",
      action: "get_preferences",
      params: {},
      context,
      driver,
    });

    expect(read.ok).toBe(true);
    if (read.ok) {
      expect(read.data).toMatchObject({
        preferences: { contact_time_preference: "after 2pm Eastern" },
      });
    }
  });
});

describe("toee_customer_memory mock — scenario 26 no inferred write", () => {
  it("never fabricates writes: preferences stay empty without an explicit upsert", async () => {
    const driver = createMockDriver(createMemoryMockHandlers());

    const read = await executeTool({
      tool: "toee_customer_memory",
      action: "get_preferences",
      params: {},
      context,
      driver,
    });

    expect(read.ok).toBe(true);
    if (read.ok) {
      expect(read.data).toMatchObject({ preferences: {} });
    }
  });

  it("exposes a baseline default registry that reads empty preferences", async () => {
    const driver = createMockDriver(memoryMockHandlers);

    const read = await executeTool({
      tool: "toee_customer_memory",
      action: "get_preferences",
      params: {},
      context,
      driver,
    });

    expect(read.ok).toBe(true);
    if (read.ok) {
      expect(read.data).toMatchObject({ preferences: {} });
    }
  });
});

describe("toee_customer_memory mock — clear and slot rules", () => {
  it("clears a stored preference slot", async () => {
    const driver = createMockDriver(
      createMemoryMockHandlers({ preferences: { channel_preference: "sms" } }),
    );
    const copilotContext: ToolExecutionContext = {
      profile: HERMES_PROFILES.internalCopilot,
      identity: verifiedIdentity,
    };

    const cleared = await executeTool({
      tool: "toee_customer_memory",
      action: "clear_preference",
      params: { key: "channel_preference" },
      context: copilotContext,
      driver,
    });

    expect(cleared.ok).toBe(true);
    if (cleared.ok) {
      expect(cleared.data).toMatchObject({
        slot: "channel_preference",
        cleared: true,
      });
    }

    const read = await executeTool({
      tool: "toee_customer_memory",
      action: "get_preferences",
      params: {},
      context: copilotContext,
      driver,
    });

    expect(read.ok).toBe(true);
    if (read.ok) {
      expect(read.data).toMatchObject({ preferences: {} });
    }
  });

  it("rejects an open-ended (non-v1) preference key per ADR-0111", async () => {
    const driver = createMockDriver(createMemoryMockHandlers());

    const result = await executeTool({
      tool: "toee_customer_memory",
      action: "upsert_preference",
      params: {
        key: "favorite_color",
        value: "blue",
        source: "explicit_customer_statement",
      },
      context,
      driver,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errorClass).toBe("unexpected_error");
    }
  });

  it("isolates preference writes by identity binding key", async () => {
    const driver = createMockDriver(createMemoryMockHandlers());

    await executeTool({
      tool: "toee_customer_memory",
      action: "upsert_preference",
      params: {
        key: "contact_time_preference",
        value: "mornings",
        source: "explicit_customer_statement",
      },
      context,
      driver,
    });

    const otherContext: ToolExecutionContext = {
      profile: HERMES_PROFILES.externalCustomerService,
      identity: {
        outcome: "verified_customer",
        shopifyCustomerId: "gid://shopify/Customer/2002",
        resolvedAt: "2026-01-01T00:00:00.000Z",
      },
    };

    const read = await executeTool({
      tool: "toee_customer_memory",
      action: "get_preferences",
      params: {},
      context: otherContext,
      driver,
    });

    expect(read.ok).toBe(true);
    if (read.ok) {
      expect(read.data).toMatchObject({ preferences: {} });
    }
  });
});
