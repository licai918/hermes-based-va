import { describe, it, expect, vi } from "vitest";
import { HERMES_PROFILES } from "@toee/shared";
import { createMockDriver } from "./mock-driver";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";
import {
  textlineMockHandlers,
  createTextlineMockHandlers,
  createTextlineMockData,
} from "./textline";

const context: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
};

describe("toee_textline_reply mock — send_message", () => {
  it("returns a captured outbound message", async () => {
    const driver = createMockDriver({ ...textlineMockHandlers });

    const result = await executeTool({
      tool: "toee_textline_reply",
      action: "send_message",
      params: { conversationId: "conv_1", body: "Thanks, your order ships today." },
      context,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        conversationId: "conv_1",
        body: "Thanks, your order ships today.",
        messageId: expect.any(String),
      });
    }
  });

  it("captures the outbound SMS in the injected outbox", async () => {
    const data = createTextlineMockData();
    const driver = createMockDriver({ ...createTextlineMockHandlers(data) });

    await executeTool({
      tool: "toee_textline_reply",
      action: "send_message",
      params: { conversationId: "conv_7", body: "On its way!" },
      context,
      driver,
    });

    expect(data.outbox).toHaveLength(1);
    expect(data.outbox[0]).toMatchObject({
      conversationId: "conv_7",
      body: "On its way!",
    });
  });

  it("echoes media_url for a Product Media Reply", async () => {
    const data = createTextlineMockData();
    const driver = createMockDriver({ ...createTextlineMockHandlers(data) });

    const result = await executeTool({
      tool: "toee_textline_reply",
      action: "send_message",
      params: {
        conversationId: "conv_9",
        body: "Here is that tire.",
        media_url: "https://cdn.example/tire.jpg",
      },
      context,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        conversationId: "conv_9",
        body: "Here is that tire.",
        mediaUrl: "https://cdn.example/tire.jpg",
      });
    }
  });

  it("is deterministic for identical input", async () => {
    const firstData = createTextlineMockData();
    const secondData = createTextlineMockData();
    const params = { conversationId: "conv_5", body: "Same message" };

    const first = await executeTool({
      tool: "toee_textline_reply",
      action: "send_message",
      params,
      context,
      driver: createMockDriver({ ...createTextlineMockHandlers(firstData) }),
    });
    const second = await executeTool({
      tool: "toee_textline_reply",
      action: "send_message",
      params,
      context,
      driver: createMockDriver({ ...createTextlineMockHandlers(secondData) }),
    });

    expect(first.ok && second.ok).toBe(true);
    if (first.ok && second.ok) {
      expect(first.data).toEqual(second.data);
    }
  });

  it("does not call any external/network API", async () => {
    const hasFetch = typeof globalThis.fetch === "function";
    const fetchSpy = hasFetch ? vi.spyOn(globalThis, "fetch") : undefined;
    const data = createTextlineMockData();
    const driver = createMockDriver({ ...createTextlineMockHandlers(data) });

    const result = await executeTool({
      tool: "toee_textline_reply",
      action: "send_message",
      params: { conversationId: "conv_2", body: "No network here." },
      context,
      driver,
    });

    expect(result.ok).toBe(true);
    if (fetchSpy) {
      expect(fetchSpy).not.toHaveBeenCalled();
      fetchSpy.mockRestore();
    }
  });
});
