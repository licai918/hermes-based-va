import type { MockHandlerRegistry } from "./mock-driver";

// A Public Site Knowledge entry rebuilt from Shopify Knowledge Sync and the
// Tavily Gap Crawl (ADR-0067). Mock fixtures stand in for the real RAG index.
export interface KnowledgePublicSiteEntry {
  title: string;
  url: string;
  snippet: string;
}

// Injectable knowledge fixtures for `toee_knowledge_search`.
// - `operationalPolicy` maps a Required Operational Policy Slot (ADR-0003) to its
//   Published Operational Policy content. A missing or empty slot yields the
//   governed no-policy fallback rather than improvised policy (ADR-0067).
// - `publicSite` is the deterministic Public Site Knowledge corpus.
export interface KnowledgeMockData {
  operationalPolicy: Record<string, string>;
  publicSite: KnowledgePublicSiteEntry[];
}

// Default fixtures. Every Required Operational Policy Slot starts unfilled
// (ADR-0003), so `search_operational_policy` returns the safe no-policy fallback
// until a later slice injects published content. The Public Site corpus carries
// a couple of neutral placeholder entries.
export const knowledgeBaselineData: KnowledgeMockData = {
  operationalPolicy: {},
  publicSite: [
    {
      title: "Contact & Store Hours",
      url: "https://www.toeetire.com/pages/contact",
      snippet: "How to reach Toee Tire support and current service hours.",
    },
    {
      title: "Shipping & Delivery",
      url: "https://www.toeetire.com/pages/shipping",
      snippet: "Overview of order delivery options and timelines.",
    },
  ],
};

function readStringParam(
  params: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = params[key];
  return typeof value === "string" ? value : undefined;
}

// Builds `toee_knowledge_search` handlers bound to the supplied fixtures. Every
// response is a pure function of (data, params): no clocks, randomness, or
// external calls, so eval runs and BFF slices get stable shapes.
export function createKnowledgeMockHandlers(
  data: KnowledgeMockData = knowledgeBaselineData,
): MockHandlerRegistry {
  return {
    toee_knowledge_search: {
      // `search_operational_policy` looks up a single slot. `slot` is the primary
      // key; `query` is accepted as an alias so callers can pass either. An empty
      // or unknown slot is `found: false` with empty content (ADR-0067 fallback).
      search_operational_policy: (params) => {
        const slot =
          readStringParam(params, "slot") ?? readStringParam(params, "query");
        const content =
          slot !== undefined ? (data.operationalPolicy[slot] ?? "") : "";
        return {
          slot: slot ?? null,
          content,
          found: content.length > 0,
        };
      },
      // `search_public_site` returns the deterministic corpus, optionally filtered
      // by a case-insensitive substring match across title and snippet.
      search_public_site: (params) => {
        const query = readStringParam(params, "query");
        const normalized = query?.trim().toLowerCase();
        const results =
          normalized === undefined || normalized === ""
            ? data.publicSite
            : data.publicSite.filter((entry) =>
                `${entry.title} ${entry.snippet}`
                  .toLowerCase()
                  .includes(normalized),
              );
        return { results: results.map((entry) => ({ ...entry })) };
      },
    },
  };
}

// Default registry wired to the baseline fixtures (knowledge reads are stateless,
// so this singleton is safe to share).
export const knowledgeMockHandlers: MockHandlerRegistry =
  createKnowledgeMockHandlers();
