import { render, screen } from "@testing-library/react";
import type { AggregateMetrics } from "@/lib/bff/admin/metrics";
import { MetricsPanel } from "./MetricsPanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function metrics(overrides: Partial<AggregateMetrics> = {}): AggregateMetrics {
  return {
    memoryInjection: { injected: 3, total: 10, rate: 0.3 },
    knowledgeSearch: { found: 2, total: 5, rate: 0.4 },
    slotsPopulatedDistribution: { "1": 0, "2": 0, "3": 0, "4": 0 },
    honoredRate: {
      live: true,
      rate: 0.9,
      sampleSize: 40,
      candidateTotal: 200,
      undetermined: 15,
      windowSeconds: 3600,
      asOf: "2026-07-24T03:00:00Z",
      label: "not yet computed",
    },
    mergeCount: 0,
    correctionCount: 0,
    proposalOutcomes: { accepted: 0, dismissed: 0, rate: null },
    selfServiceUsage: 0,
    l6ConfirmedEntries: 0,
    latency: latency(),
    deletionSuccess: {
      windowDays: 30,
      erasedBindings: 5,
      flaggedBindings: 2,
      residueBindings: 1,
      reappearedBindings: 1,
      rate: 0.6,
      flaggedSlots: { contact_time_preference: 2 },
      label: "Share of erases whose bindings are still empty.",
    },
    lifecycle: [
      count("conflict_overwrites", "Conflicting L4 overwrites", 7),
      count("pollution_rejected_writes", "L4 writes rejected by the injection scan", 3),
      count("privacy_deflection_self_service", "Customer self-service clears", 4),
      count("privacy_deflection_erasures", "Whole-binding erasures (forget-me)", 1),
      count("prompt_layer_drops_L7", "L7 dropped from a prompt (deadline)", 0),
    ],
    knobs: {
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
    },
    ...overrides,
  };
}

function count(
  key: string,
  label: string,
  value: number | null,
): AggregateMetrics["lifecycle"][number] {
  return { key, label, detail: `what ${key} counts, and what it does not`, value };
}

// S18/FR-26: per-layer latency tiles + the total-vs-SLO tile.
function tile(
  metric: string,
  over: Partial<AggregateMetrics["latency"]["total"]> = {},
): AggregateMetrics["latency"]["total"] {
  return {
    metric,
    layer: "L4",
    label: `Label ${metric}`,
    p50Ms: null,
    p95Ms: null,
    samples: 0,
    budgetMs: null,
    inSloTotal: true,
    breached: null,
    ...over,
  };
}

function latency(
  over: Partial<AggregateMetrics["latency"]> = {},
): AggregateMetrics["latency"] {
  return {
    sloP95Ms: 150,
    notMeasuredLabel: "Not yet measured (no latency samples on this deployment)",
    total: tile("latency_pre_turn_total", {
      layer: "L4+L6+L7",
      label: "Pre-turn reads, total",
      p50Ms: 31.5,
      p95Ms: 128.25,
      samples: 400,
      budgetMs: 150,
      inSloTotal: false,
      breached: false,
    }),
    layers: [
      tile("latency_l4_load", {
        label: "L4 customer memory read",
        p50Ms: 12.5,
        p95Ms: 40,
        samples: 400,
      }),
      tile("knowledge_search", {
        layer: "L5",
        label: "L5 knowledge retrieval",
        p50Ms: 210,
        p95Ms: 900,
        samples: 25,
        budgetMs: 800,
        inSloTotal: false,
        breached: true,
      }),
    ],
    ...over,
  };
}

describe("MetricsPanel honored-rate caption", () => {
  afterEach(() => vi.unstubAllGlobals());

  // 0.0.4 minor cleanup: the sub-line dropped `undetermined` (collapsing two
  // distinct stages -- determinately-scored vs eligible-pre-cap -- into one ratio
  // that read as "only looked at 40 of 200"), and the wording over-asserted that
  // memory was injected at reply time. The RATE is honest; only the caption needs
  // fixing.
  it("surfaces undetermined and the honest 'customer memory on file' wording", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(metrics())));

    render(<MetricsPanel />);
    const caption = await screen.findByText(/customer memory on file/i);
    const text = caption.textContent ?? "";

    // `undetermined` (15) is surfaced -- no longer dropped.
    expect(text).toContain("15");
    expect(text).toMatch(/undetermined/i);
    // "scored" (40) is distinguished from the eligible population (200).
    expect(text).toContain("40");
    expect(text).toContain("200");
    // Honest wording: eligibility is "has customer memory on file", NOT "memory
    // injected at reply time"; and the old misleading phrasing is gone.
    expect(text).not.toMatch(/recent turns sampled/i);
    expect(text).not.toMatch(/inject/i);
    // Provenance stays.
    expect(text).toMatch(/as of/i);
  });

  it("still shows the honest not-yet-computed label before the first run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          metrics({
            honoredRate: {
              live: false,
              rate: null,
              sampleSize: null,
              candidateTotal: null,
              undetermined: null,
              windowSeconds: null,
              asOf: null,
              label: "Not yet computed",
            },
          }),
        ),
      ),
    );

    render(<MetricsPanel />);
    // Both the tile value and the honest sub-label read "Not yet computed".
    expect((await screen.findAllByText("Not yet computed")).length).toBeGreaterThan(0);
  });
});

describe("MetricsPanel per-layer latency tiles (S18, FR-26)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders p50/p95 per layer and the total against the 150ms SLO line", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(metrics())));

    render(<MetricsPanel />);
    const section = await screen.findByRole("region", { name: /read latency/i });

    // The per-layer histogram: both statistics, not just one.
    expect(section.textContent).toContain("12.5");
    expect(section.textContent).toContain("40");
    // The total tile carries the owner's recorded line.
    expect(section.textContent).toContain("128.25");
    expect(section.textContent).toMatch(/150\s*ms/);
    expect(section.textContent).toMatch(/p95/i);
  });

  it("renders a breach visibly rather than as another number", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(metrics())));

    render(<MetricsPanel />);
    // L5 is over its own 800ms budget in this fixture; the L4 tile is not
    // budgeted at all. Exactly one tile may claim a breach.
    const breaches = await screen.findAllByText(/over budget/i);
    expect(breaches).toHaveLength(1);
    expect(breaches[0]?.closest("[data-metric]")?.getAttribute("data-metric")).toBe(
      "knowledge_search",
    );
  });

  it("shows the honest not-measured label instead of a zero before any sample", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          metrics({
            latency: latency({
              total: tile("latency_pre_turn_total", {
                label: "Pre-turn reads, total",
                budgetMs: 150,
              }),
              layers: [tile("latency_l4_load", { label: "L4 customer memory read" })],
            }),
          }),
        ),
      ),
    );

    render(<MetricsPanel />);
    const section = await screen.findByRole("region", { name: /read latency/i });
    expect(section.textContent).toMatch(/not yet measured/i);
    // A "0 ms" tile would read as the best possible latency on a deployment
    // that has measured nothing, and a green "within SLO" would be a lie.
    // Digit-anchored so the SLO caption's own "150 ms" isn't mistaken for it.
    expect(section.textContent).not.toMatch(/(^|[^\d.])0(\.0)? ?ms/);
    expect(section.textContent).not.toMatch(/within/i);
  });
});

describe("MetricsPanel lifecycle block (S22, FR-34a)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders every lifecycle count with the scope its detail carries", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(metrics())));

    render(<MetricsPanel />);
    const section = await screen.findByRole("region", { name: /memory lifecycle/i });

    for (const key of [
      "conflict_overwrites",
      "pollution_rejected_writes",
      "privacy_deflection_self_service",
      "privacy_deflection_erasures",
      "prompt_layer_drops_L7",
    ]) {
      const tile = section.querySelector(`[data-lifecycle="${key}"]`);
      expect(tile, key).not.toBeNull();
      // Value AND its caveat -- a tile that dropped `detail` would render a
      // number nobody can read correctly.
      expect(tile?.textContent).toContain("what " + key + " counts");
    }
    expect(section.textContent).toContain("7");
    expect(section.textContent).toContain("3");
  });

  it("renders a component with no source as not-recorded, never as a zero", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(metrics({ lifecycle: [count("conflict_overwrites", "Conflicts", null)] })),
      ),
    );

    render(<MetricsPanel />);
    const section = await screen.findByRole("region", { name: /memory lifecycle/i });
    const tile = section.querySelector('[data-lifecycle="conflict_overwrites"]');
    expect(tile?.textContent).toMatch(/not recorded/i);
    expect(tile?.textContent).not.toMatch(/(^|[^\d])0([^\d]|$)/);
  });

  it("renders deletion success as its components, never as a bare rate", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(metrics())));

    render(<MetricsPanel />);
    const section = await screen.findByRole("region", { name: /memory lifecycle/i });
    const tile = section.querySelector('[data-lifecycle="deletion_success"]');
    // Residue and re-appearance are different failures and are shown apart; the
    // 30-day window is what the number is scoped to.
    expect(tile?.textContent).toMatch(/residue/i);
    expect(tile?.textContent).toMatch(/re-?appear/i);
    expect(tile?.textContent).toContain("30");
    expect(tile?.textContent).toContain("5");
  });

  it("reports a null deletion-success rate as not computed, never as 100%", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          metrics({
            deletionSuccess: {
              windowDays: 30,
              erasedBindings: 0,
              flaggedBindings: 0,
              residueBindings: 0,
              reappearedBindings: 0,
              rate: null,
              flaggedSlots: {},
              label: "Share of erases whose bindings are still empty.",
            },
          }),
        ),
      ),
    );

    render(<MetricsPanel />);
    const tile = (
      await screen.findByRole("region", { name: /memory lifecycle/i })
    ).querySelector('[data-lifecycle="deletion_success"]');
    expect(tile?.textContent).toMatch(/no erases/i);
    expect(tile?.textContent).not.toContain("100%");
  });
});

describe("MetricsPanel knob panel (S22, D14)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders each knob's value, where it lives, and its env override", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(metrics())));

    render(<MetricsPanel />);
    const section = await screen.findByRole("region", { name: /knob/i });
    expect(section.textContent).toContain("LEXICON_GLOSSARY_LIMIT");
    expect(section.textContent).toContain("20");
    expect(section.textContent).toContain("hermes_runtime.tool_backend");
    expect(section.textContent).toContain("LEXICON_SELECTION");
  });

  it("says plainly that it changes nothing, and offers no control that could (D14)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(metrics())));

    render(<MetricsPanel />);
    const section = await screen.findByRole("region", { name: /knob/i });
    expect(section.textContent).toMatch(/read-only/i);
    // NFR-3: a knob moves by deploy-time config commit. A control here would be
    // an ungoverned write surface -- so there must not be one to click.
    expect(section.querySelectorAll("button, input, select, textarea")).toHaveLength(0);
  });

  it("says the backend reports no knobs rather than rendering an empty panel", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(metrics({ knobs: null }))));

    render(<MetricsPanel />);
    const section = await screen.findByRole("region", { name: /knob/i });
    expect(section.textContent).toMatch(/not reported by this backend/i);
  });
});
