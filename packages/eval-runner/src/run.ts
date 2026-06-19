import { evaluateScenario } from "./assertions";
import {
  loadPolicyPublishSuite,
  loadScenario,
  loadSuite,
} from "./fixtures";
import { stubAgentHarness, type AgentHarness } from "./harness";
import {
  buildReport,
  writeReport,
  type EvalReport,
  type ReportMeta,
  type ScenarioOutcome,
} from "./report";
import type { EvalSuite, MergedScenario } from "./types";

export interface RunOptions {
  suite: EvalSuite;
  evalDir: string;
  scenarioId?: string;
  slot?: string;
  agent?: AgentHarness;
  meta?: ReportMeta;
  // When true, the report is written under eval/reports (set by the CLI).
  write?: boolean;
}

export interface RunResult {
  report: EvalReport;
  reportPath?: string;
}

function selectScenarios(options: RunOptions): MergedScenario[] {
  if (options.suite === "policy_publish") {
    if (options.slot === undefined) {
      throw new Error("policy_publish runs require a --slot.");
    }
    return loadPolicyPublishSuite(options.evalDir, options.slot);
  }
  if (options.scenarioId !== undefined) {
    return [loadScenario(options.suite, options.scenarioId, options.evalDir)];
  }
  return loadSuite(options.suite, options.evalDir);
}

// Loads the selected scenarios, runs each through the agent harness (stub by
// default), checks the standard assertion package, and assembles the JSON
// report. Optionally writes it to eval/reports.
export async function runSuite(options: RunOptions): Promise<RunResult> {
  const agent = options.agent ?? stubAgentHarness;
  const scenarios = selectScenarios(options);

  const scenarioOutcomes: ScenarioOutcome[] = [];
  for (const scenario of scenarios) {
    const turn = await agent.runTurn(scenario);
    scenarioOutcomes.push({
      scenarioId: scenario.scenarioId,
      title: scenario.title,
      severity: scenario.assertions.max_severity,
      outcomes: evaluateScenario(scenario, turn),
    });
  }

  const report = buildReport(options.suite, scenarioOutcomes, options.meta);
  const reportPath = options.write
    ? writeReport(options.evalDir, report)
    : undefined;

  return { report, ...(reportPath !== undefined ? { reportPath } : {}) };
}
