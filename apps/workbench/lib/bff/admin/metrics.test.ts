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
    deletion_success: rawDeletionSuccess(),
    lifecycle: rawLifecycle(),
    knobs: rawKnobs(),
    ...overrides,
  };
}

// S11/FR-14 shape, mirroring toee_hermes...memory.deletion_success_payload.
function rawDeletionSuccess(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    window_days: 30,
    erased_bindings: 5,
    flagged_bindings: 2,
    residue_bindings: 1,
    reappeared_bindings: 1,
    rate: 0.6,
    flagged_slots: { contact_time_preference: 2 },
    label: "share of erases whose bindings are still empty",
    ...over,
  };
}

// S22/FR-34a shape, mirroring toee_hermes.lifecycle_metrics.lifecycle_payload.
// Every count is a DIFFERENT number, so a mapper that read the wrong row or
// collapsed the list would show up as a wrong value rather than as a coincidence.
function rawCount(key: string, value: number | null, over: Record<string, unknown> = {}) {
  return {
    key,
    label: `label for ${key}`,
    detail: `what ${key} counts, and what it deliberately does not`,
    value,
    ...over,
  };
}

function rawLifecycle(): unknown[] {
  return [
    rawCount("conflict_overwrites", 7),
    rawCount("pollution_rejected_writes", 3),
    rawCount("privacy_deflection_self_service", 4),
    rawCount("privacy_deflection_erasures", 1),
    rawCount("prompt_layer_drops_L4", 0),
    rawCount("prompt_layer_drops_L6", 2),
    rawCount("prompt_layer_drops_L7", 9),
  ];
}

function rawKnobs(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    label: "Read-only. These knobs move by deploy-time config commit.",
    knobs: [
      {
        key: "LEXICON_GLOSSARY_LIMIT",
        label: "L7 prompt glossary window",
        value: "20",
        source: "hermes_runtime.tool_backend",
        env: null,
        note: "how many confirmed entries the prompt glossary may carry",
      },
      {
        key: "LEXICON_SELECTION",
        label: "L7 glossary selection strategy (effective)",
        value: "newest",
        source: "hermes_runtime.tool_backend",
        env: "LEXICON_SELECTION",
        note: "fail-safe: an unrecognised value resolves to the shipped behaviour",
      },
    ],
    ...over,
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
    // Scoped past the S22 lifecycle block, whose privacy-deflection row is an
    // honestly labelled proxy (FR-34a, owner ⑤). A whole-body grep cannot tell
    // "still secretly a proxy" from "correctly says it is one"; everything the
    // old scan covered on these two tiles is still covered.
    const { lifecycle: _lifecycle, ...rest } = body as Record<string, unknown>;
    expect(JSON.stringify(rest)).not.toContain("proxy");
  });

  // --- 0.0.5 S22 (FR-34a): the lifecycle half ---------------------------------

  it("carries every FR-34a lifecycle count with the scope its label claims", async () => {
    const client = apiClient(async () => dispatchResponse(rawMetrics()));
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as { lifecycle: AggregateMetrics["lifecycle"] };

    const byKey = Object.fromEntries(body.lifecycle.map((c) => [c.key, c.value]));
    expect(byKey).toEqual({
      conflict_overwrites: 7,
      pollution_rejected_writes: 3,
      privacy_deflection_self_service: 4,
      privacy_deflection_erasures: 1,
      prompt_layer_drops_L4: 0,
      prompt_layer_drops_L6: 2,
      prompt_layer_drops_L7: 9,
    });
    // The house rule S14 set and S26 extended: no count reaches a renderer
    // without the caveat that makes it readable.
    for (const count of body.lifecycle) {
      expect(count.label.length).toBeGreaterThan(0);
      expect(count.detail.length).toBeGreaterThan(0);
    }
  });

  it("refuses a lifecycle count that arrives without its scope rather than showing the bare number", async () => {
    // A count whose label or detail was lost in transit is a number nobody can
    // read correctly -- and 0 vs "0 of what" is exactly the difference this
    // panel exists to keep. Same stance as mapHealth's scope/basis refusal.
    for (const missing of [{ label: "" }, { detail: "" }]) {
      const client = apiClient(async () =>
        dispatchResponse(
          rawMetrics({ lifecycle: [rawCount("conflict_overwrites", 7, missing)] }),
        ),
      );
      expect((await handleGetAggregateMetricsViaApi(client)).status).toBe(502);
    }
  });

  it("keeps a lifecycle component with no source honestly absent, never a zero", async () => {
    // `null` is "nothing feeds this yet" and 0 is "it happened zero times" --
    // the S21 `no_stale_use` rule, applied to a count.
    const client = apiClient(async () =>
      dispatchResponse(rawMetrics({ lifecycle: [rawCount("conflict_overwrites", null)] })),
    );
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as { lifecycle: AggregateMetrics["lifecycle"] };
    expect(body.lifecycle[0]?.value).toBeNull();
  });

  it("carries S11's deletion-success components, not just the rate (FR-14)", async () => {
    const client = apiClient(async () => dispatchResponse(rawMetrics()));
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as { deletionSuccess: AggregateMetrics["deletionSuccess"] };

    expect(body.deletionSuccess.erasedBindings).toBe(5);
    expect(body.deletionSuccess.flaggedBindings).toBe(2);
    expect(body.deletionSuccess.residueBindings).toBe(1);
    expect(body.deletionSuccess.reappearedBindings).toBe(1);
    expect(body.deletionSuccess.rate).toBe(0.6);
    expect(body.deletionSuccess.windowDays).toBe(30);
    expect(body.deletionSuccess.flaggedSlots).toEqual({ contact_time_preference: 2 });
  });

  it("reports a null deletion-success rate as not-computed, never as 100%", async () => {
    const client = apiClient(async () =>
      dispatchResponse(
        rawMetrics({
          deletion_success: rawDeletionSuccess({
            erased_bindings: 0,
            flagged_bindings: 0,
            residue_bindings: 0,
            reappeared_bindings: 0,
            rate: null,
            flagged_slots: {},
          }),
        }),
      ),
    );
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as { deletionSuccess: AggregateMetrics["deletionSuccess"] };
    expect(body.deletionSuccess.rate).toBeNull();
    expect(body.deletionSuccess.erasedBindings).toBe(0);
  });

  it("carries the read-only knob panel with each knob's source and env override", async () => {
    const client = apiClient(async () => dispatchResponse(rawMetrics()));
    const res = await handleGetAggregateMetricsViaApi(client);
    const body = (await res.json()) as { knobs: AggregateMetrics["knobs"] };

    expect(body.knobs?.label).toContain("Read-only");
    const glossary = body.knobs?.knobs.find((k) => k.key === "LEXICON_GLOSSARY_LIMIT");
    expect(glossary?.value).toBe("20");
    expect(glossary?.source).toBe("hermes_runtime.tool_backend");
    // No env override for this one; the next knob has one.
    expect(glossary?.env).toBeNull();
    expect(body.knobs?.knobs.find((k) => k.key === "LEXICON_SELECTION")?.env).toBe(
      "LEXICON_SELECTION",
    );
  });

  it("accepts a backend that reports no knob values at all (the mock twin)", async () => {
    // toee_hermes must not import hermes_runtime, so the mock twin sends null
    // rather than a copy of the constants. Null is renderable as "not reported
    // by this backend"; a 502 here would break the whole panel on dev.
    const client = apiClient(async () => dispatchResponse(rawMetrics({ knobs: null })));
    const res = await handleGetAggregateMetricsViaApi(client);
    expect(res.status).toBe(200);
    expect(((await res.json()) as AggregateMetrics).knobs).toBeNull();
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
