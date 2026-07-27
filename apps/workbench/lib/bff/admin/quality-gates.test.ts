import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_STALE_SECONDS,
  handleGetQualityGates,
  type QualityGatesView,
} from "./quality-gates";

// Real artifact filenames are `{kind}-{stamp}.json` with a lexicographically-sortable
// stamp (strftime %Y%m%dT%H%M%S%fZ). The reader selects the newest report per kind by
// that filename stamp, so tests use stamp-shaped names where greater string = newer.
function stamp(run: number): string {
  return `20260101T00${String(run).padStart(6, "0")}Z`;
}

let dir: string;

beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), "gate-reports-"));
});

afterEach(async () => {
  vi.restoreAllMocks();
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

  it("keeps only the NEWEST artifact per kind by filename stamp -- even if the older file has a newer mtime", async () => {
    // Older stamp, but we deliberately give it the NEWER mtime to prove selection follows
    // the filename stamp (one consistent key), not the filesystem clock.
    await writeArtifact("recall-20260701T000000000000Z.json", recallArtifact("2026-07-01T00:00:00Z", "20/30 = 67% (bar: 80%)"));
    await writeArtifact("recall-20260724T030000000000Z.json", recallArtifact("2026-07-24T03:00:00Z", "24/30 = 80% (bar: 80%)"));
    const newer = new Date("2026-08-01T00:00:00Z");
    await fs.utimes(path.join(dir, "recall-20260701T000000000000Z.json"), newer, newer);

    const body = await view(Date.parse("2026-07-24T04:00:00Z"));
    expect(body.reports).toHaveLength(1);
    expect(body.reports[0]!.rows[0]!.result).toBe("24/30 = 80% (bar: 80%)");
  });

  it("does NOT starve a quiet kind when other kinds emit far more recent files (mtime-cap regression)", async () => {
    // recall goes silent after one old run; latency + judge each emit 100 newer files.
    // Under the old newest-50-by-mtime cap, recall's lone oldest-mtime file fell outside
    // the top 50 of 200+ newer files -> recall vanished from the panel. Group-by-kind reads
    // each kind's newest, so recall's last report always shows (labeled stale if need be).
    const old = new Date("2026-01-01T00:00:00Z");
    await writeArtifact(`recall-${stamp(0)}.json`, recallArtifact("2026-01-01T00:00:00Z"));
    await fs.utimes(path.join(dir, `recall-${stamp(0)}.json`), old, old);

    const recent = new Date("2026-07-24T00:00:00Z");
    for (const kind of ["latency", "judge"] as const) {
      for (let run = 1; run <= 100; run++) {
        const name = `${kind}-${stamp(run)}.json`;
        await writeArtifact(name, {
          kind,
          generated_at: "2026-07-24T00:00:00Z",
          source: `python -m ... ${kind}`,
          source_run: `run/${run}`,
          rows: [{ name: `${kind} row`, command: "cmd", result: `run ${run}`, passed: kind === "judge" ? null : true, note: null }],
        });
        await fs.utimes(path.join(dir, name), recent, recent);
      }
    }

    const body = await view(Date.parse("2026-07-24T04:00:00Z"));
    expect(body.reports.map((r) => r.kind)).toContain("recall");
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

  it("forces judge rows to advisory even if an artifact wrongly carried passed:true (NFR-7)", async () => {
    await writeArtifact("judge-bad.json", {
      kind: "judge",
      generated_at: "2026-07-24T03:00:00Z",
      source: "python -m hermes_runtime.advisory_judge_report",
      source_run: null,
      rows: [{ name: "Judge", command: "cmd", result: "precision 1.000", passed: true, note: null }],
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

  it("reads O(kinds) files (one newest-per-kind), not O(all-history), and stays correct", async () => {
    // The reports dir grows one file per gate run and nothing prunes it. The panel only
    // shows the newest report per kind, and filenames carry a sortable stamp -- so the
    // reader should read ~one file per kind (the lexicographically-greatest name), NOT a
    // 50-file mtime cap. Model many runs and assert reads == number of kinds.
    const kinds = ["recall", "latency", "judge"] as const;
    const runs = 100; // 100 runs * 3 kinds = 300 files
    const base = Date.parse("2026-01-01T00:00:00Z");
    for (let run = 0; run < runs; run++) {
      const generatedAt = new Date(base + run * 60_000).toISOString();
      for (const kind of kinds) {
        await writeArtifact(`${kind}-${stamp(run)}.json`, {
          kind,
          generated_at: generatedAt,
          source: `python -m ... ${kind}`,
          source_run: `run/${run}`,
          rows: [{ name: `${kind} row`, command: "cmd", result: `run ${run}`, passed: kind === "judge" ? null : true, note: null }],
        });
      }
    }

    const readSpy = vi.spyOn(fs, "readFile");
    const body = await view(base + runs * 60_000 + 1000);

    // O(kinds) reads -- exactly one per kind, not the whole dir nor a 50-file cap.
    expect(readSpy.mock.calls.length).toBe(kinds.length);

    // Newest-per-kind (by filename stamp) is correct: each kind's newest is the last run.
    expect(body.reports.map((r) => r.kind)).toEqual(["recall", "latency", "judge"]);
    for (const r of body.reports) {
      expect(r.rows[0]!.result).toBe(`run ${runs - 1}`);
    }
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
