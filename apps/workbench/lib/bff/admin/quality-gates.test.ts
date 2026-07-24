import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_STALE_SECONDS,
  handleGetQualityGates,
  type QualityGatesView,
} from "./quality-gates";

let dir: string;

beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), "gate-reports-"));
});

afterEach(async () => {
  await fs.rm(dir, { recursive: true, force: true });
});

async function writeArtifact(name: string, body: unknown): Promise<void> {
  await fs.writeFile(path.join(dir, name), JSON.stringify(body), "utf-8");
}

function recallArtifact(generatedAt: string, result = "22/30 = 73% (bar: 80%)") {
  return {
    kind: "recall",
    generated_at: generatedAt,
    source: "python -m hermes_runtime.knowledge.gates recall",
    source_run: "https://ci.example/run/1",
    rows: [
      {
        name: "Recall@3 (FR-7)",
        command: "python -m hermes_runtime.knowledge.gates recall",
        result,
        passed: false,
        note: null,
      },
    ],
  };
}

async function view(now: number, staleThresholdSeconds?: number): Promise<QualityGatesView> {
  const res = await handleGetQualityGates(dir, { now, staleThresholdSeconds });
  expect(res.status).toBe(200);
  return (await res.json()) as QualityGatesView;
}

describe("handleGetQualityGates", () => {
  it("returns honest empty when the reports directory does not exist (no-report)", async () => {
    const res = await handleGetQualityGates(path.join(dir, "does-not-exist"));
    expect(res.status).toBe(200);
    const body = (await res.json()) as QualityGatesView;
    expect(body.reports).toEqual([]);
    expect(body.staleThresholdSeconds).toBe(DEFAULT_STALE_SECONDS);
  });

  it("returns honest empty when the directory has no artifacts", async () => {
    const body = await view(Date.now());
    expect(body.reports).toEqual([]);
  });

  it("serves an artifact's real rows + as-of + provenance, fresh -> not stale", async () => {
    const generatedAt = "2026-07-24T03:00:00Z";
    await writeArtifact("recall-1.json", recallArtifact(generatedAt));
    const now = Date.parse(generatedAt) + 60_000; // 1 min later

    const body = await view(now);
    expect(body.reports).toHaveLength(1);
    const r = body.reports[0]!;
    expect(r.kind).toBe("recall");
    expect(r.generatedAt).toBe(generatedAt);
    expect(r.sourceRun).toBe("https://ci.example/run/1");
    expect(r.rows[0]!.result).toBe("22/30 = 73% (bar: 80%)");
    expect(r.rows[0]!.passed).toBe(false);
    expect(r.stale).toBe(false);
    expect(r.ageSeconds).toBe(60);
  });

  it("labels an artifact older than the threshold as stale", async () => {
    const generatedAt = "2026-01-01T00:00:00Z";
    await writeArtifact("recall-old.json", recallArtifact(generatedAt));
    const now = Date.parse(generatedAt) + (DEFAULT_STALE_SECONDS + 1) * 1000;

    const body = await view(now);
    expect(body.reports[0]!.stale).toBe(true);
  });

  it("keeps only the NEWEST artifact per kind (source-run provenance stays current)", async () => {
    await writeArtifact("recall-old.json", recallArtifact("2026-07-01T00:00:00Z", "20/30 = 67% (bar: 80%)"));
    await writeArtifact("recall-new.json", recallArtifact("2026-07-24T03:00:00Z", "24/30 = 80% (bar: 80%)"));

    const body = await view(Date.parse("2026-07-24T04:00:00Z"));
    expect(body.reports).toHaveLength(1);
    expect(body.reports[0]!.rows[0]!.result).toBe("24/30 = 80% (bar: 80%)");
  });

  it("preserves passed=null for advisory (judge) rows -- never coerced to PASS/FAIL", async () => {
    await writeArtifact("judge-1.json", {
      kind: "judge",
      generated_at: "2026-07-24T03:00:00Z",
      source: "python -m hermes_runtime.advisory_judge_report",
      source_run: null,
      rows: [
        {
          name: "Judge precision/recall (FR-29)",
          command: "python -m hermes_runtime.advisory_judge_report",
          result: "precision 1.000, recall 1.000, accuracy 0.923 (13 fixtures, 1 undetermined)",
          passed: null,
          note: "advisory",
        },
      ],
    });

    const body = await view(Date.parse("2026-07-24T04:00:00Z"));
    expect(body.reports[0]!.rows[0]!.passed).toBeNull();
  });

  it("orders reports recall, latency, judge for a deterministic panel", async () => {
    await writeArtifact("judge-1.json", { kind: "judge", generated_at: "2026-07-24T03:00:00Z", source: "j", source_run: null, rows: [] });
    await writeArtifact("latency-1.json", { kind: "latency", generated_at: "2026-07-24T03:00:00Z", source: "l", source_run: null, rows: [] });
    await writeArtifact("recall-1.json", recallArtifact("2026-07-24T03:00:00Z"));

    const body = await view(Date.parse("2026-07-24T04:00:00Z"));
    expect(body.reports.map((r) => r.kind)).toEqual(["recall", "latency", "judge"]);
  });

  it("skips a malformed artifact but still serves the valid ones (no crash, no junk)", async () => {
    await writeArtifact("recall-1.json", recallArtifact("2026-07-24T03:00:00Z"));
    await fs.writeFile(path.join(dir, "broken.json"), "{ not json", "utf-8");
    await writeArtifact("bad-shape.json", { kind: "recall", source: "x" }); // missing generated_at + rows

    const body = await view(Date.parse("2026-07-24T04:00:00Z"));
    expect(body.reports).toHaveLength(1);
    expect(body.reports[0]!.kind).toBe("recall");
  });
});
