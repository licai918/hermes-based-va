import { describe, it, expect } from "vitest";
import { HERMES_PROFILES } from "@toee/shared";
import { executeTool } from "../execute-tool";
import type { ToolExecutionContext } from "../tool-gate";
import { createMockDriver } from "./mock-driver";
import {
  createKnowledgeMockHandlers,
  knowledgeBaselineData,
  knowledgeMockHandlers,
} from "./knowledge";

const context: ToolExecutionContext = {
  profile: HERMES_PROFILES.externalCustomerService,
};

describe("toee_knowledge_search mock — search_operational_policy", () => {
  it("returns a governed no-policy result for an empty/unpublished slot", async () => {
    const driver = createMockDriver({ ...knowledgeMockHandlers });

    const result = await executeTool({
      tool: "toee_knowledge_search",
      action: "search_operational_policy",
      params: { slot: "business_hours_service_boundaries" },
      context,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({
        slot: "business_hours_service_boundaries",
        content: "",
        found: false,
      });
    }
  });

  it("returns injected published content for a slot (fixture-friendly)", async () => {
    const driver = createMockDriver(
      createKnowledgeMockHandlers({
        ...knowledgeBaselineData,
        operationalPolicy: {
          business_hours_service_boundaries: "Open Mon-Fri 9-5 ET.",
        },
      }),
    );

    const result = await executeTool({
      tool: "toee_knowledge_search",
      action: "search_operational_policy",
      params: { slot: "business_hours_service_boundaries" },
      context,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({
        slot: "business_hours_service_boundaries",
        content: "Open Mon-Fri 9-5 ET.",
        found: true,
      });
    }
  });

  it("resolves the slot from the query alias when slot is omitted", async () => {
    const driver = createMockDriver(
      createKnowledgeMockHandlers({
        operationalPolicy: { payment_payment_link_rules: "Card on file only." },
        publicSite: [],
      }),
    );

    const result = await executeTool({
      tool: "toee_knowledge_search",
      action: "search_operational_policy",
      params: { query: "payment_payment_link_rules" },
      context,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toMatchObject({
        slot: "payment_payment_link_rules",
        content: "Card on file only.",
        found: true,
      });
    }
  });
});

describe("toee_knowledge_search mock — search_public_site", () => {
  it("returns a deterministic, non-empty baseline result set", async () => {
    const driver = createMockDriver(knowledgeMockHandlers);

    const first = await executeTool({
      tool: "toee_knowledge_search",
      action: "search_public_site",
      params: {},
      context,
      driver,
    });
    const second = await executeTool({
      tool: "toee_knowledge_search",
      action: "search_public_site",
      params: {},
      context,
      driver,
    });

    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    if (first.ok && second.ok) {
      expect(first.data).toEqual(second.data);
      const data = first.data as { results: unknown[] };
      expect(Array.isArray(data.results)).toBe(true);
      expect(data.results.length).toBeGreaterThan(0);
    }
  });

  it("filters baseline results by a case-insensitive query", async () => {
    const driver = createMockDriver(
      createKnowledgeMockHandlers({
        operationalPolicy: {},
        publicSite: [
          {
            title: "Store Hours",
            url: "https://example.test/hours",
            snippet: "We are open daily.",
          },
          {
            title: "Shipping",
            url: "https://example.test/shipping",
            snippet: "Ships in 2 days.",
          },
        ],
      }),
    );

    const result = await executeTool({
      tool: "toee_knowledge_search",
      action: "search_public_site",
      params: { query: "HOURS" },
      context,
      driver,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({
        results: [
          {
            title: "Store Hours",
            url: "https://example.test/hours",
            snippet: "We are open daily.",
          },
        ],
      });
    }
  });
});
