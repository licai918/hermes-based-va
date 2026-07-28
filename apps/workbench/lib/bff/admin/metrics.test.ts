import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleGetAggregateMetricsViaApi, type AggregateMetrics } from "./metrics";

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
    honored_rate: {
      live: false,
      rate: null,
      sample_size: null,
      candidate_total: null,
      undetermined_count: null,
      window_seconds: null,
      as_of: null,
      label: "advisory, judge-sampled -- not yet computed",
    },
    merge_count: 2,
    correction_count: 1,
    proposal_outcomes: { accepted: 1, dismissed: 1, rate: 0.5 },
    self_service_usage: 3,
    l6_confirmed_entries: 2,
    latency: rawLatency(),
    ...overrides,
  };
}

// S18/FR-26 shape, mirroring hermes_runtime.latency's payload.
function rawTile(
  metric: string,
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    metric,
    layer: "L4",
    label: `label for ${metric}`,
    p50_ms: null,
    p95_ms: null,
    samples: 0,
    budget_ms: null,
    in_slo_total: true,
    breached: null,
    ...over,
  };
}

function rawLatency(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    slo_p95_ms: 150,
    not_measured_label: "Not yet measured (no latency samples on this deployment)",
    total: rawTile("latency_pre_turn_total", {
      layer: "L4+L6+L7",
      p50_ms: 31.5,
      p95_ms: 128.25,
      samples: 400,
      budget_ms: 150,
      in_slo_total: false,
      breached: false,
    }),
    layers: [
      rawTile("latency_l4_load", { p50_ms: 12.5, p95_ms: 40, samples: 400 }),
      rawTile("knowledge_search", {
        layer: "L5",
        p50_ms: 210,
        p95_ms: 900,
        samples: 25,
        budget_ms: 800,
        in_slo_total: false,
        breached: true,
      }),
    ],
    ...over,
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

  it("honestly labels honored_rate as not-yet-computed, never a silent zero (S22)", async () => {
    const client = apiClient(async () => dispatchResponse(rawMetrics()));
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as { honoredRate: AggregateMetrics["honoredRate"] };
    // Not-computed: live false, rate null, and the provenance fields null -- never
    // a fabricated 0.
    expect(body.honoredRate.live).toBe(false);
    expect(body.honoredRate.rate).toBeNull();
    expect(body.honoredRate.sampleSize).toBeNull();
    expect(body.honoredRate.asOf).toBeNull();
    expect(body.honoredRate.label.length).toBeGreaterThan(0);
  });

  it("carries a live honored_rate aggregate with sample/population/as-of provenance (S22/FR-31)", async () => {
    const client = apiClient(async () =>
      dispatchResponse(
        rawMetrics({
          honored_rate: {
            live: true,
            rate: 0.8333,
            sample_size: 12,
            candidate_total: 40,
            undetermined_count: 2,
            window_seconds: 604800,
            as_of: "2026-07-24T03:00:00+00:00",
            label: "advisory, judge-sampled honored leg over 12 of 40 turns",
          },
        }),
      ),
    );
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as { honoredRate: AggregateMetrics["honoredRate"] };
    expect(body.honoredRate.live).toBe(true);
    expect(body.honoredRate.rate).toBe(0.8333);
    expect(body.honoredRate.sampleSize).toBe(12);
    expect(body.honoredRate.candidateTotal).toBe(40);
    expect(body.honoredRate.undetermined).toBe(2);
    expect(body.honoredRate.asOf).toBe("2026-07-24T03:00:00+00:00");
  });

  it("carries self-service usage and L6 confirmed entries as real counts, no proxy wrapper (S21/FR-30)", async () => {
    const client = apiClient(async () => dispatchResponse(rawMetrics()));
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as Record<string, unknown>;
    // Plain integers now (like mergeCount/correctionCount) -- the proxy flag
    // and label are gone from these two tiles.
    expect(body.selfServiceUsage).toBe(3);
    expect(body.l6ConfirmedEntries).toBe(2);
    expect(JSON.stringify(body)).not.toContain("proxy");
  });

  it("carries per-layer p50/p95 and the SLO verdict per tile (S18/FR-26)", async () => {
    const client = apiClient(async () => dispatchResponse(rawMetrics()));
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as { latency: AggregateMetrics["latency"] };

    expect(body.latency.sloP95Ms).toBe(150);
    expect(body.latency.total.p95Ms).toBe(128.25);
    expect(body.latency.total.budgetMs).toBe(150);
    expect(body.latency.total.breached).toBe(false);

    const l4 = body.latency.layers.find((t) => t.metric === "latency_l4_load");
    expect(l4?.p50Ms).toBe(12.5);
    expect(l4?.samples).toBe(400);
    // Measured but not budgeted: this slice ships no deadline of its own (S19
    // owns enforcement), so an unbudgeted layer renders percentiles and no verdict.
    expect(l4?.budgetMs).toBeNull();
    expect(l4?.breached).toBeNull();
    expect(l4?.inSloTotal).toBe(true);

    // L5 is judged against its OWN 800ms budget and excluded from the SLO total
    // (D5.2): 900ms p95 breaches that budget, not the 150ms line.
    const l5 = body.latency.layers.find((t) => t.metric === "knowledge_search");
    expect(l5?.budgetMs).toBe(800);
    expect(l5?.breached).toBe(true);
    expect(l5?.inSloTotal).toBe(false);
  });

  it("keeps an unmeasured latency tile honestly unmeasured, never a zero (S18)", async () => {
    const client = apiClient(async () =>
      dispatchResponse(
        rawMetrics({
          latency: rawLatency({
            total: rawTile("latency_pre_turn_total", { budget_ms: 150 }),
            layers: [rawTile("latency_l4_load")],
          }),
        }),
      ),
    );
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as { latency: AggregateMetrics["latency"] };
    expect(body.latency.total.p95Ms).toBeNull();
    expect(body.latency.total.samples).toBe(0);
    // `false` here would render a green "within SLO" tile for a deployment that
    // has never measured anything.
    expect(body.latency.total.breached).toBeNull();
    expect(body.latency.notMeasuredLabel.length).toBeGreaterThan(0);
  });

  it("rejects a latency block whose tiles are malformed rather than passing it through", async () => {
    const client = apiClient(async () =>
      dispatchResponse(rawMetrics({ latency: rawLatency({ layers: ["not a tile"] }) })),
    );
    expect((await handleGetAggregateMetricsViaApi(client)).status).toBe(502);
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
