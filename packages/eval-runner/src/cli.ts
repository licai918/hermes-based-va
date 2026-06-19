#!/usr/bin/env node
import { resolve } from "node:path";
import { runSuite } from "./run";
import type { EvalSuite } from "./types";

const SUITES: readonly EvalSuite[] = [
  "text_first_launch",
  "email_go_live",
  "policy_publish",
];

interface CliArgs {
  suite: EvalSuite;
  scenarioId?: string;
  slot?: string;
}

export function parseArgs(argv: string[]): CliArgs {
  let suite: EvalSuite = "text_first_launch";
  let scenarioId: string | undefined;
  let slot: string | undefined;

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    switch (arg) {
      case "--suite":
        if (next === undefined || !SUITES.includes(next as EvalSuite)) {
          throw new Error(`--suite must be one of: ${SUITES.join(", ")}`);
        }
        suite = next as EvalSuite;
        i += 1;
        break;
      case "--scenario":
        if (next === undefined) {
          throw new Error("--scenario requires a scenario id.");
        }
        scenarioId = next;
        i += 1;
        break;
      case "--slot":
        if (next === undefined) {
          throw new Error("--slot requires a policy slot name.");
        }
        slot = next;
        i += 1;
        break;
      default:
        throw new Error(`Unknown argument "${arg}".`);
    }
  }

  return {
    suite,
    ...(scenarioId !== undefined ? { scenarioId } : {}),
    ...(slot !== undefined ? { slot } : {}),
  };
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const evalDir = resolve(process.cwd(), "eval");

  const { report, reportPath } = await runSuite({
    suite: args.suite,
    evalDir,
    write: true,
    ...(args.scenarioId !== undefined ? { scenarioId: args.scenarioId } : {}),
    ...(args.slot !== undefined ? { slot: args.slot } : {}),
  });

  const { summary } = report;
  for (const scenario of report.scenarios) {
    const status = scenario.passed ? "PASS" : `FAIL [${scenario.severity}]`;
    console.log(`${status}  ${scenario.scenario_id}  ${scenario.title}`);
    for (const failure of scenario.failed_assertions) {
      console.log(`        - ${failure.type}/${failure.name}: ${failure.detail}`);
    }
  }
  console.log(
    `\n${report.suite}: ${summary.passed}/${summary.total} passed | failed_high=${summary.failed_high} failed_medium=${summary.failed_medium}`,
  );
  if (reportPath !== undefined) {
    console.log(`Report: ${reportPath}`);
  }
  if (report.signoff_required) {
    console.log("Medium-severity failures require sign_off_medium_failure.");
  }

  // Go-live gate (ADR-0074, ADR-0121): high-severity failures block promotion.
  process.exit(summary.failed_high > 0 ? 1 : 0);
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
