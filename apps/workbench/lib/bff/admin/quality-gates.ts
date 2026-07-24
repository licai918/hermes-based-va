// QualityGatesPanel live read (0.0.4 S23, FR-32). The knowledge gates harness
// (`hermes_runtime.knowledge.gates`) and the advisory judge runnable
// (`hermes_runtime.advisory_judge_report`) each emit a small JSON artifact per run
// into a reports directory (`GATE_REPORTS_DIR`, else <repo-root>/.reports/gates).
// This serves the NEWEST artifact per kind so the panel shows real numbers +
// "as of" + provenance instead of hand-copied statics.
//
// Governed like the sibling admin panels: the /api/admin/quality-gates route wraps
// this in withSession (ADR-0093 admin gating). Unlike the Hermes-dispatch reads in
// this folder, the data source here is on-disk dev-harness artifacts (there is no
// Hermes tool for them and inventing one would be far heavier than the artifacts'
// file emit) -- the ADMIN GATE is the withSession route, same as every other panel;
// only the source differs. The path is fixed, never user-supplied (no traversal).
//
// Honesty (FR-32): no artifact -> honest empty (never a fabricated number); an
// artifact older than the stale threshold -> `stale: true` so the panel labels it;
// a malformed file is skipped (logged), never crashing the panel or passing junk
// through.
import { existsSync, promises as fs } from "node:fs";
import path from "node:path";
import { json } from "../respond";

// Gates run manually / per-PR (judge), not on a tight cadence, so "stale" is
// generous. ponytail: single flat threshold; per-kind cadences if a gate ever
// needs a tighter freshness bar.
export const DEFAULT_STALE_SECONDS = 30 * 24 * 60 * 60; // 30 days

// Panel-row order for a deterministic render; unknown kinds sort after, alpha.
const KIND_ORDER = ["recall", "latency", "judge"];

export interface GateRow {
  name: string;
  command: string;
  result: string;
  passed: boolean | null; // null = advisory (no PASS/FAIL), e.g. the judge report
  note: string | null;
}

export interface QualityGateReport {
  kind: string;
  source: string;
  sourceRun: string | null;
  generatedAt: string;
  ageSeconds: number;
  stale: boolean;
  rows: GateRow[];
}

export interface QualityGatesView {
  reports: QualityGateReport[];
  staleThresholdSeconds: number;
}

type ParsedArtifact = {
  kind: string;
  source: string;
  sourceRun: string | null;
  generatedAt: string;
  generatedAtMs: number;
  rows: GateRow[];
};

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parseRow(raw: unknown): GateRow | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const name = asString(r.name);
  const command = asString(r.command);
  const result = asString(r.result);
  if (name === null || command === null || result === null) return null;
  return {
    name,
    command,
    result,
    passed: typeof r.passed === "boolean" ? r.passed : null,
    note: asString(r.note),
  };
}

function parseArtifact(raw: unknown): ParsedArtifact | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const kind = asString(r.kind);
  const source = asString(r.source);
  const generatedAt = asString(r.generated_at);
  if (!kind || !source || !generatedAt) return null;
  const generatedAtMs = Date.parse(generatedAt);
  if (Number.isNaN(generatedAtMs)) return null;
  if (!Array.isArray(r.rows)) return null;
  const rows = r.rows.map(parseRow);
  if (rows.some((row) => row === null)) return null;
  // Defense-in-depth (NFR-7): a judge artifact is ADVISORY by definition -- force
  // passed=null so even a wrongly-emitted judge row can never render PASS/FAIL.
  const gateRows = (rows as GateRow[]).map((row) =>
    kind === "judge" ? { ...row, passed: null } : row,
  );
  return {
    kind,
    source,
    sourceRun: asString(r.source_run),
    generatedAt,
    generatedAtMs,
    rows: gateRows,
  };
}

function orderIndex(kind: string): number {
  const i = KIND_ORDER.indexOf(kind);
  return i === -1 ? KIND_ORDER.length : i;
}

export async function handleGetQualityGates(
  reportsDir: string,
  opts: { now?: number; staleThresholdSeconds?: number } = {},
): Promise<Response> {
  const now = opts.now ?? Date.now();
  const staleThresholdSeconds = opts.staleThresholdSeconds ?? DEFAULT_STALE_SECONDS;

  let files: string[];
  try {
    files = await fs.readdir(reportsDir);
  } catch (err) {
    // No reports directory yet -> honest empty, not a crash.
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return json<QualityGatesView>({ reports: [], staleThresholdSeconds });
    }
    throw err;
  }

  const newestByKind = new Map<string, ParsedArtifact>();
  for (const file of files) {
    if (!file.endsWith(".json")) continue;
    let parsed: ParsedArtifact | null = null;
    try {
      const text = await fs.readFile(path.join(reportsDir, file), "utf-8");
      parsed = parseArtifact(JSON.parse(text));
    } catch {
      parsed = null; // unreadable / non-JSON -> skip
    }
    if (!parsed) {
      console.warn(`[quality-gates] skipping unparseable gate report: ${file}`);
      continue;
    }
    const current = newestByKind.get(parsed.kind);
    if (!current || parsed.generatedAtMs > current.generatedAtMs) {
      newestByKind.set(parsed.kind, parsed);
    }
  }

  const reports: QualityGateReport[] = [...newestByKind.values()]
    .map((p) => {
      const ageSeconds = Math.max(0, Math.floor((now - p.generatedAtMs) / 1000));
      return {
        kind: p.kind,
        source: p.source,
        sourceRun: p.sourceRun,
        generatedAt: p.generatedAt,
        ageSeconds,
        stale: ageSeconds > staleThresholdSeconds,
        rows: p.rows,
      };
    })
    .sort((a, b) => orderIndex(a.kind) - orderIndex(b.kind) || a.kind.localeCompare(b.kind));

  return json<QualityGatesView>({ reports, staleThresholdSeconds });
}

// Route-side dir resolution: `GATE_REPORTS_DIR` env, else the repo-root
// `.reports/gates` the Python harness also defaults to (found by walking up for the
// pnpm-workspace.yaml marker, since the workbench dev-server cwd is the app dir).
export function resolveReportsDir(): string {
  const env = process.env.GATE_REPORTS_DIR;
  if (env) return env;
  let dir = process.cwd();
  for (let i = 0; i < 8; i++) {
    if (existsSync(path.join(dir, "pnpm-workspace.yaml"))) {
      return path.join(dir, ".reports", "gates");
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return path.resolve(process.cwd(), ".reports", "gates");
}

export function resolveStaleThresholdSeconds(): number {
  const raw = process.env.GATE_REPORT_STALE_SECONDS;
  const n = raw ? Number(raw) : NaN;
  return Number.isFinite(n) && n > 0 ? n : DEFAULT_STALE_SECONDS;
}
