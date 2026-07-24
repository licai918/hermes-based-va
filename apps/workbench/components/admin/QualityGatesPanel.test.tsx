import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QualityGatesPanel } from "./QualityGatesPanel";
import type { QualityGatesView } from "@/lib/bff/admin/quality-gates";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function stubView(view: QualityGatesView) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse(view)),
  );
}

const RECALL_REPORT = {
  kind: "recall",
  source: "python -m hermes_runtime.knowledge.gates recall",
  sourceRun: "https://ci.example/run/42",
  generatedAt: "2026-07-24T03:00:00Z",
  ageSeconds: 60,
  stale: false,
  rows: [
    {
      name: "Recall@3 (FR-7)",
      command: "python -m hermes_runtime.knowledge.gates recall",
      result: "24/30 = 80% (bar: 80%)",
      passed: true,
      note: null,
    },
  ],
};

describe("QualityGatesPanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders the latest artifact's real values with an 'as of' timestamp + source run", async () => {
    stubView({ reports: [RECALL_REPORT], staleThresholdSeconds: 1000 });
    render(<QualityGatesPanel />);

    expect(await screen.findByText("24/30 = 80% (bar: 80%)")).toBeInTheDocument();
    expect(screen.getByText("python -m hermes_runtime.knowledge.gates recall")).toBeInTheDocument();
    expect(screen.getByText(/^as of /)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "source run" })).toHaveAttribute(
      "href",
      "https://ci.example/run/42",
    );
    expect(screen.getByText("PASS")).toBeInTheDocument();
  });

  it("labels a stale report rather than presenting it as current (no-stale-lie)", async () => {
    stubView({
      reports: [{ ...RECALL_REPORT, stale: true }],
      staleThresholdSeconds: 1000,
    });
    render(<QualityGatesPanel />);

    expect(await screen.findByText(/may be stale/)).toBeInTheDocument();
  });

  it("shows an honest empty state when no report artifacts exist (no fabricated number)", async () => {
    stubView({ reports: [], staleThresholdSeconds: 1000 });
    render(<QualityGatesPanel />);

    expect(await screen.findByText(/No gate reports available yet/)).toBeInTheDocument();
    expect(screen.queryByText("PASS")).toBeNull();
    expect(screen.queryByText("FAIL")).toBeNull();
  });

  it("renders the judge report as ADVISORY, never PASS/FAIL (FR-29)", async () => {
    stubView({
      reports: [
        {
          kind: "judge",
          source: "python -m hermes_runtime.advisory_judge_report",
          sourceRun: null,
          generatedAt: "2026-07-24T03:00:00Z",
          ageSeconds: 60,
          stale: false,
          rows: [
            {
              name: "Judge precision/recall (FR-29)",
              command: "python -m hermes_runtime.advisory_judge_report",
              result: "precision 1.000, recall 1.000, accuracy 0.923 (13 fixtures, 1 undetermined)",
              passed: null,
              note: "advisory",
            },
          ],
        },
      ],
      staleThresholdSeconds: 1000,
    });
    render(<QualityGatesPanel />);

    expect(await screen.findByText("ADVISORY")).toBeInTheDocument();
    expect(screen.queryByText("PASS")).toBeNull();
    expect(screen.queryByText("FAIL")).toBeNull();
  });
});
