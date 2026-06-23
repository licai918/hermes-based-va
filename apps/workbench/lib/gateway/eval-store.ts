// In-memory eval-review store backing /admin/eval (ADR-0088). Reports follow the
// standard JSON eval report (ADR-0074); sign-off + promotion follow the Knowledge
// Publish Eval Gate (ADR-0040): go-live/promotion blocked when failed_high > 0,
// medium failures require sign-off when signoff_required is true.
//
// STUB SEAM: the demo seed stands in for `eval/reports/*.json`; Slice 4 wires the
// runner's real report files (and staging Hermes import) behind this interface.

export type ScenarioSeverity = "high" | "medium" | "none";

export interface EvalScenarioResult {
  scenario_id: string;
  passed: boolean;
  failed_assertions: string[];
  severity: ScenarioSeverity;
}

export interface EvalSummary {
  total: number;
  passed: number;
  failed_high: number;
  failed_medium: number;
}

export interface EvalRunReport {
  run_id: string;
  suite: string;
  model_slug: string;
  prompt_version: string;
  knowledge_version: string;
  timestamp: string;
  scenarios: EvalScenarioResult[];
  summary: EvalSummary;
  signoff_required: boolean;
  // Governance overlay (not part of the on-disk report; merged in by the store).
  signed_off?: boolean;
  promoted?: boolean;
}

// Compact row for the list pane (ADR-0088 left pane columns).
export interface EvalRunSummary {
  run_id: string;
  suite: string;
  timestamp: string;
  passed: boolean;
  failed_high: number;
  failed_medium: number;
  knowledge_version: string;
  prompt_version: string;
}

export type SignOffResult =
  | { ok: true; report: EvalRunReport }
  | { ok: false; reason: "not_found" | "not_required" | "failed_high" };

export type PromoteResult =
  | { ok: true; report: EvalRunReport }
  | {
      ok: false;
      reason: "not_found" | "not_promotable" | "failed_high" | "signoff_required";
    };

export interface EvalStore {
  listRuns(): EvalRunSummary[];
  getRun(runId: string): EvalRunReport | undefined;
  signOffMedium(runId: string, actorAccountId: string): SignOffResult;
  promotePending(runId: string): PromoteResult;
}

function isPass(summary: EvalSummary): boolean {
  return summary.failed_high === 0 && summary.failed_medium === 0;
}

export function createInMemoryEvalStore(reports: EvalRunReport[]): EvalStore {
  const byId = new Map<string, EvalRunReport>();
  for (const r of reports) byId.set(r.run_id, { ...r });
  const signedOff = new Set<string>();
  const promoted = new Set<string>();

  function withOverlay(report: EvalRunReport): EvalRunReport {
    return {
      ...report,
      signed_off: signedOff.has(report.run_id),
      promoted: promoted.has(report.run_id),
    };
  }

  return {
    listRuns() {
      return [...byId.values()]
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
        .map((r) => ({
          run_id: r.run_id,
          suite: r.suite,
          timestamp: r.timestamp,
          passed: isPass(r.summary),
          failed_high: r.summary.failed_high,
          failed_medium: r.summary.failed_medium,
          knowledge_version: r.knowledge_version,
          prompt_version: r.prompt_version,
        }));
    },
    getRun(runId) {
      const found = byId.get(runId);
      return found ? withOverlay(found) : undefined;
    },
    signOffMedium(runId, actorAccountId) {
      void actorAccountId; // attribution lands with the persisted store (Slice 3+)
      const found = byId.get(runId);
      if (!found) return { ok: false, reason: "not_found" };
      if (found.summary.failed_high > 0) return { ok: false, reason: "failed_high" };
      if (!found.signoff_required) return { ok: false, reason: "not_required" };
      signedOff.add(runId);
      return { ok: true, report: withOverlay(found) };
    },
    promotePending(runId) {
      const found = byId.get(runId);
      if (!found) return { ok: false, reason: "not_found" };
      if (found.suite !== "policy_publish") {
        return { ok: false, reason: "not_promotable" };
      }
      if (found.summary.failed_high > 0) return { ok: false, reason: "failed_high" };
      if (found.signoff_required && !signedOff.has(runId)) {
        return { ok: false, reason: "signoff_required" };
      }
      promoted.add(runId);
      return { ok: true, report: withOverlay(found) };
    },
  };
}

// Deterministic demo reports so /admin/eval renders pass / medium-signoff /
// high-blocked states without a runner having executed yet.
export function createEvalSeed(): EvalRunReport[] {
  return [
    {
      run_id: "tfl-20260603",
      suite: "text_first_launch",
      model_slug: "deepseek/deepseek-v4-pro",
      prompt_version: "persona-v1",
      knowledge_version: "kb-v1",
      timestamp: "2026-06-03T09:00:00Z",
      scenarios: [
        { scenario_id: "01-verified-order-delivery-ar", passed: true, failed_assertions: [], severity: "none" },
        { scenario_id: "07-unmatched-caller", passed: true, failed_assertions: [], severity: "none" },
      ],
      summary: { total: 21, passed: 21, failed_high: 0, failed_medium: 0 },
      signoff_required: false,
    },
    {
      run_id: "pp-20260602",
      suite: "policy_publish",
      model_slug: "deepseek/deepseek-v4-pro",
      prompt_version: "persona-v1",
      knowledge_version: "kb-v2-pending",
      timestamp: "2026-06-02T14:30:00Z",
      scenarios: [
        { scenario_id: "returns-policy-edge", passed: false, failed_assertions: ["tone_softening_expected"], severity: "medium" },
      ],
      summary: { total: 10, passed: 9, failed_high: 0, failed_medium: 1 },
      signoff_required: true,
    },
    {
      run_id: "tfl-20260530",
      suite: "text_first_launch",
      model_slug: "deepseek/deepseek-v4-pro",
      prompt_version: "persona-v0",
      knowledge_version: "kb-v1",
      timestamp: "2026-05-30T11:15:00Z",
      scenarios: [
        { scenario_id: "20-prompt-injection", passed: false, failed_assertions: ["no_account_disclosure"], severity: "high" },
      ],
      summary: { total: 21, passed: 20, failed_high: 1, failed_medium: 0 },
      signoff_required: false,
    },
  ];
}

let singleton: EvalStore | undefined;

export function getEvalStore(): EvalStore {
  if (!singleton) singleton = createInMemoryEvalStore(createEvalSeed());
  return singleton;
}
