import type { AgentTurnResult } from "./harness";
import type {
  MergedScenario,
  ScenarioAssertions,
  ToolCallAssertion,
} from "./types";

// One checked assertion. `passed: false` contributes to the scenario failing at
// the scenario's max_severity (ADR-0072, ADR-0074).
export interface AssertionOutcome {
  type: "behavioral" | "tool" | "disclosure" | "text" | "memory";
  name: string;
  passed: boolean;
  detail: string;
}

function matchesCall(
  call: { tool: string; action: string },
  expected: ToolCallAssertion,
): boolean {
  if (call.tool !== expected.tool) {
    return false;
  }
  return expected.action === undefined || call.action === expected.action;
}

function describeCall(expected: ToolCallAssertion): string {
  return expected.action ? `${expected.tool}.${expected.action}` : expected.tool;
}

function evalBehavioral(
  behavioral: Record<string, unknown>,
  result: AgentTurnResult,
): AssertionOutcome[] {
  const outcomes: AssertionOutcome[] = [];
  for (const [name, expected] of Object.entries(behavioral)) {
    let actual: unknown;
    switch (name) {
      case "case_created":
        actual = result.caseCreated;
        break;
      case "case_urgency":
        actual = result.caseUrgency;
        break;
      case "contact_reason":
        actual = result.contactReason;
        break;
      case "alternate_address_not_verified":
        actual = result.alternateAddressNotVerified ?? false;
        break;
      default:
        actual = undefined;
    }
    outcomes.push({
      type: "behavioral",
      name,
      passed: actual === expected,
      detail: `expected ${name}=${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    });
  }
  return outcomes;
}

function evalTool(
  tool: NonNullable<ScenarioAssertions["tool"]>,
  result: AgentTurnResult,
): AssertionOutcome[] {
  const outcomes: AssertionOutcome[] = [];
  for (const expected of tool.expect_calls ?? []) {
    const found = result.toolCalls.some((call) => matchesCall(call, expected));
    outcomes.push({
      type: "tool",
      name: `expect_call ${describeCall(expected)}`,
      passed: found,
      detail: found ? "called" : "expected tool call was not made",
    });
  }
  for (const forbidden of tool.forbidden_tools ?? []) {
    const called = result.toolCalls.some((call) =>
      matchesCall(call, forbidden),
    );
    outcomes.push({
      type: "tool",
      name: `forbidden ${describeCall(forbidden)}`,
      passed: !called,
      detail: called ? "forbidden tool call was made" : "not called",
    });
  }
  return outcomes;
}

function evalDisclosure(
  disclosure: Record<string, boolean>,
  result: AgentTurnResult,
): AssertionOutcome[] {
  return Object.entries(disclosure).map(([name, expected]) => {
    const actual = result.disclosures[name];
    return {
      type: "disclosure",
      name,
      passed: actual === expected,
      detail: `expected ${name}=${expected}, got ${JSON.stringify(actual)}`,
    };
  });
}

function evalText(
  text: NonNullable<ScenarioAssertions["text"]>,
  result: AgentTurnResult,
): AssertionOutcome[] {
  const haystack = result.outboundText.toLowerCase();
  const outcomes: AssertionOutcome[] = [];
  for (const phrase of text.must_contain ?? []) {
    const passed = haystack.includes(phrase.toLowerCase());
    outcomes.push({
      type: "text",
      name: `must_contain "${phrase}"`,
      passed,
      detail: passed ? "present" : "missing from outbound text",
    });
  }
  for (const phrase of text.must_not_contain ?? []) {
    const passed = !haystack.includes(phrase.toLowerCase());
    outcomes.push({
      type: "text",
      name: `must_not_contain "${phrase}"`,
      passed,
      detail: passed ? "absent" : "present in outbound text",
    });
  }
  return outcomes;
}

function evalMemory(
  memory: NonNullable<ScenarioAssertions["memory_assertions"]>,
  result: AgentTurnResult,
): AssertionOutcome[] {
  const outcomes: AssertionOutcome[] = [];
  const didUpsert =
    result.memoryUpserts.length > 0 ||
    result.toolCalls.some(
      (call) =>
        call.tool === "toee_customer_memory" &&
        call.action === "upsert_preference",
    );

  if (memory.expect_upsert === true) {
    outcomes.push({
      type: "memory",
      name: "expect_upsert",
      passed: didUpsert,
      detail: didUpsert ? "upsert occurred" : "no preference upsert observed",
    });
  }
  if (memory.expect_upsert_slot !== undefined) {
    const slot = memory.expect_upsert_slot;
    const passed = result.memoryUpserts.includes(slot);
    outcomes.push({
      type: "memory",
      name: `expect_upsert_slot ${slot}`,
      passed,
      detail: passed ? "slot upserted" : `slot ${slot} was not upserted`,
    });
  }
  if (memory.forbid_inferred_upsert === true) {
    outcomes.push({
      type: "memory",
      name: "forbid_inferred_upsert",
      passed: !didUpsert,
      detail: didUpsert ? "an inferred upsert was made" : "no inferred upsert",
    });
  }
  if (memory.honor_injected_preference === true) {
    const passed = result.honoredInjectedPreference === true;
    outcomes.push({
      type: "memory",
      name: "honor_injected_preference",
      passed,
      detail: passed
        ? "injected preference honored"
        : "injected preference not honored (or re-asked)",
    });
  }
  return outcomes;
}

// Runs the standard assertion package (ADR-0072 + ADR-0118) for one scenario
// against an agent turn result. Returns one outcome per checked assertion.
export function evaluateScenario(
  scenario: MergedScenario,
  result: AgentTurnResult,
): AssertionOutcome[] {
  const a = scenario.assertions;
  const outcomes: AssertionOutcome[] = [];
  if (a.behavioral) {
    outcomes.push(...evalBehavioral(a.behavioral, result));
  }
  if (a.tool) {
    outcomes.push(...evalTool(a.tool, result));
  }
  if (a.disclosure) {
    outcomes.push(...evalDisclosure(a.disclosure, result));
  }
  if (a.text) {
    outcomes.push(...evalText(a.text, result));
  }
  if (a.memory_assertions) {
    outcomes.push(...evalMemory(a.memory_assertions, result));
  }
  return outcomes;
}
