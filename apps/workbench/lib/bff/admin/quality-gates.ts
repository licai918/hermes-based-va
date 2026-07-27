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

  // The reports dir grows one file per gate run and nothing prunes it, so reading EVERY
  // .json is O(all-history). The panel only ever shows the newest report per kind, and
  // filenames are `{kind}-{stamp}.json` where stamp = strftime("%Y%m%dT%H%M%S%fZ") -- a
  // lexicographically-sortable timestamp, and neither the kind nor the stamp contains a
  // `-`. So parse the kind as the substring before the first `-`, group by kind, and take
  // the lexicographically-greatest name per kind (= newest) WITHOUT reading. We then read
  // + parse only that ~one-per-kind file. This is O(kinds) reads (no kind can be starved
  // by a noisier sibling) and uses ONE consistent key -- the filename stamp -- for both
  // newest-per-kind selection and read-bounding. Files not matching the shape are ignored.
  const namesByKind = new Map<string, string[]>();
  for (const file of files) {
    if (!file.endsWith(".json")) continue;
    const dash = file.indexOf("-");
    if (dash <= 0) continue; // no `{kind}-{stamp}` shape -> ignore
    const kind = file.slice(0, dash);
    const list = namesByKind.get(kind);
    if (list) list.push(file);
    else namesByKind.set(kind, [file]);
  }

  const reports: QualityGateReport[] = [];
  for (const names of namesByKind.values()) {
    // Newest first by the sortable stamp; read down only until the first file that parses,
    // so a malformed newest falls back to the prior report for that kind (honest, no crash)
    // rather than dropping the kind entirely.
    names.sort((a, b) => (a < b ? 1 : a > b ? -1 : 0));
    for (const file of names) {
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
      const ageSeconds = Math.max(0, Math.floor((now - parsed.generatedAtMs) / 1000));
      reports.push({
        kind: parsed.kind,
        source: parsed.source,
        sourceRun: parsed.sourceRun,
        generatedAt: parsed.generatedAt,
        ageSeconds,
        stale: ageSeconds > staleThresholdSeconds,
        rows: parsed.rows,
      });
      break; // first parseable name = newest usable report for this kind
    }
  }

  reports.sort((a, b) => orderIndex(a.kind) - orderIndex(b.kind) || a.kind.localeCompare(b.kind));
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
