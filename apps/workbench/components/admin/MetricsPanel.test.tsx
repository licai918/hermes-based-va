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
    ...overrides,
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
