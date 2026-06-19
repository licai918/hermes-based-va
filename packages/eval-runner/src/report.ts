import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { AssertionOutcome } from "./assertions";
import type { EvalSeverity } from "./types";

export interface FailedAssertion {
  type: string;
  name: string;
  detail: string;
}

export interface ScenarioReport {
  scenario_id: string;
  title: string;
  passed: boolean;
  severity: EvalSeverity;
  failed_assertions: FailedAssertion[];
}

export interface EvalReportSummary {
  total: number;
  passed: number;
  failed_high: number;
  failed_medium: number;
}

// Standard JSON eval report (ADR-0074). The source of truth for
// toee_eval_review and the CI artifact trail.
export interface EvalReport {
  run_id: string;
  suite: string;
  model_slug: string;
  prompt_version: string;
  knowledge_version: string;
  scenarios: ScenarioReport[];
  summary: EvalReportSummary;
  signoff_required: boolean;
}

// Per-scenario evaluation result fed into the report builder.
export interface ScenarioOutcome {
  scenarioId: string;
  title: string;
  severity: EvalSeverity;
  outcomes: AssertionOutcome[];
}

export interface ReportMeta {
  runId?: string;
  modelSlug?: string;
  promptVersion?: string;
  knowledgeVersion?: string;
}

export function buildReport(
  suite: string,
  scenarioOutcomes: ScenarioOutcome[],
  meta: ReportMeta = {},
): EvalReport {
  const scenarios: ScenarioReport[] = scenarioOutcomes.map((scenario) => {
    const failed = scenario.outcomes.filter((outcome) => !outcome.passed);
    return {
      scenario_id: scenario.scenarioId,
      title: scenario.title,
      passed: failed.length === 0,
      severity: scenario.severity,
      failed_assertions: failed.map((outcome) => ({
        type: outcome.type,
        name: outcome.name,
        detail: outcome.detail,
      })),
    };
  });

  const failedScenarios = scenarios.filter((scenario) => !scenario.passed);
  const summary: EvalReportSummary = {
    total: scenarios.length,
    passed: scenarios.length - failedScenarios.length,
    failed_high: failedScenarios.filter((s) => s.severity === "high").length,
    failed_medium: failedScenarios.filter((s) => s.severity === "medium")
      .length,
  };

  return {
    run_id: meta.runId ?? `${suite}-${Date.now()}`,
    suite,
    model_slug: meta.modelSlug ?? "stub",
    prompt_version: meta.promptVersion ?? "v0",
    knowledge_version: meta.knowledgeVersion ?? "v0",
    scenarios,
    summary,
    signoff_required: summary.failed_medium > 0,
  };
}

// Writes the report to eval/reports/<run_id>.json and returns the path.
export function writeReport(evalDir: string, report: EvalReport): string {
  const reportsDir = join(evalDir, "reports");
  mkdirSync(reportsDir, { recursive: true });
  const path = join(reportsDir, `${report.run_id}.json`);
  writeFileSync(path, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  return path;
}
