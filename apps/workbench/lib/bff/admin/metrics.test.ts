import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleGetAggregateMetricsViaApi } from "./metrics";

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    actorAccountId: "seed-supervisor",
    fetchImpl,
  });
}

type SentDispatch = { tool: string; action: string; params: Record<string, unknown> };

function dispatchResponse(data: unknown): Response {
  return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
}

function rawMetrics(overrides: Record<string, unknown> = {}) {
  return {
    memory_injection: { injected: 2, total: 3, rate: 0.6667 },
    knowledge_search: { found: 1, total: 3, rate: 0.3333 },
    slots_populated_distribution: { "1": 2, "2": 1, "3": 0, "4": 0 },
    honored_rate: { live: false, rate: null, label: "advisory, judge-sampled" },
    merge_count: 2,
    correction_count: 1,
    proposal_outcomes: { accepted: 1, dismissed: 1, rate: 0.5 },
    self_service_usage: { count: 1, proxy: true, label: "proxy: clears only" },
    l6_confirmed_entries: { count: 1, proxy: true, label: "proxy: confirmed L6 rows" },
    ...overrides,
  };
}

describe("handleGetAggregateMetricsViaApi", () => {
  it("dispatches get_aggregate_metrics with no params and carries every FR-28 metric", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse(rawMetrics());
    });

    const res = await handleGetAggregateMetricsViaApi(client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;

    // ① acceptance: the payload must carry EVERY FR-28 metric.
    expect(body).toHaveProperty("memoryInjection");
    expect(body).toHaveProperty("knowledgeSearch");
    expect(body).toHaveProperty("slotsPopulatedDistribution");
    expect(body).toHaveProperty("honoredRate");
    expect(body).toHaveProperty("mergeCount");
    expect(body).toHaveProperty("correctionCount");
    expect(body).toHaveProperty("proposalOutcomes");
    expect(body).toHaveProperty("selfServiceUsage");
    expect(body).toHaveProperty("l6ConfirmedEntries");

    expect(body.memoryInjection).toEqual({ injected: 2, total: 3, rate: 0.6667 });
    expect(body.knowledgeSearch).toEqual({ found: 1, total: 3, rate: 0.3333 });
    expect(body.slotsPopulatedDistribution).toEqual({ "1": 2, "2": 1, "3": 0, "4": 0 });
    expect(body.mergeCount).toBe(2);
    expect(body.correctionCount).toBe(1);

    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_metrics");
    expect(sent?.action).toBe("get_aggregate_metrics");
    expect(sent?.params).toEqual({});
  });

  it("honestly labels honored_rate as non-live/advisory, never a silent zero", async () => {
    const client = apiClient(async () => dispatchResponse(rawMetrics()));
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as { honoredRate: { live: boolean; rate: number | null; label: string } };
    expect(body.honoredRate.live).toBe(false);
    expect(body.honoredRate.rate).toBeNull();
    expect(body.honoredRate.label.length).toBeGreaterThan(0);
  });

  it("carries the proxy labels for self-service usage and L6 confirmed entries", async () => {
    const client = apiClient(async () => dispatchResponse(rawMetrics()));
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as {
      selfServiceUsage: { count: number; proxy: boolean; label: string };
      l6ConfirmedEntries: { count: number; proxy: boolean; label: string };
    };
    expect(body.selfServiceUsage).toMatchObject({ count: 1, proxy: true });
    expect(body.selfServiceUsage.label.length).toBeGreaterThan(0);
    expect(body.l6ConfirmedEntries).toMatchObject({ count: 1, proxy: true });
    expect(body.l6ConfirmedEntries.label.length).toBeGreaterThan(0);
  });

  it("maps a governed denial to its per-class status (ADR-0104)", async () => {
    const res = await handleGetAggregateMetricsViaApi(
      apiClient(
        async () =>
          new Response(
            JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
            { status: 200 },
          ),
      ),
    );
    expect(res.status).toBe(403);
  });

  it("rejects a malformed payload rather than passing it through", async () => {
    const client = apiClient(async () => dispatchResponse({ memory_injection: "not an object" }));
    const res = await handleGetAggregateMetricsViaApi(client);
    // Same convention as mapAgentExperienceEntry/mapMemoryAuditView: a shape
    // the mapper can't parse is a governed unexpected_error -> 502, not a raw
    // passthrough and not an uncaught crash.
    expect(res.status).toBe(502);
  });
});
