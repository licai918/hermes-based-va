import { describe, expect, it } from "vitest";
import { evaluateScenario, type AssertionOutcome } from "./assertions";
import type { AgentTurnResult } from "./harness";
import type { MergedScenario, ScenarioAssertions } from "./types";

function scenarioWith(assertions: ScenarioAssertions): MergedScenario {
  return { assertions } as unknown as MergedScenario;
}

function turn(overrides: Partial<AgentTurnResult> = {}): AgentTurnResult {
  return {
    outboundText: "",
    toolCalls: [],
    caseCreated: false,
    disclosures: {},
    memoryUpserts: [],
    ...overrides,
  };
}

function failures(outcomes: AssertionOutcome[]): AssertionOutcome[] {
  return outcomes.filter((outcome) => !outcome.passed);
}

describe("behavioral assertions", () => {
  it("passes when case_created matches", () => {
    const outcomes = evaluateScenario(
      scenarioWith({ behavioral: { case_created: true }, max_severity: "high" }),
      turn({ caseCreated: true }),
    );
    expect(failures(outcomes)).toHaveLength(0);
  });

  it("fails when case_created mismatches", () => {
    const outcomes = evaluateScenario(
      scenarioWith({ behavioral: { case_created: true }, max_severity: "high" }),
      turn({ caseCreated: false }),
    );
    expect(failures(outcomes)).toHaveLength(1);
  });
});

describe("tool assertions", () => {
  const assertions: ScenarioAssertions = {
    tool: {
      expect_calls: [{ tool: "toee_shopify_read", action: "get_order" }],
      forbidden_tools: [
        { tool: "toee_square_payment_link", action: "send_payment_link" },
      ],
    },
    max_severity: "high",
  };

  it("passes when expected calls happen and forbidden ones do not", () => {
    const outcomes = evaluateScenario(
      scenarioWith(assertions),
      turn({ toolCalls: [{ tool: "toee_shopify_read", action: "get_order", ok: true }] }),
    );
    expect(failures(outcomes)).toHaveLength(0);
  });

  it("fails when an expected call is missing", () => {
    const outcomes = evaluateScenario(scenarioWith(assertions), turn());
    expect(failures(outcomes).some((o) => o.name.includes("expect_call"))).toBe(
      true,
    );
  });

  it("fails when a forbidden call is made", () => {
    const outcomes = evaluateScenario(
      scenarioWith(assertions),
      turn({
        toolCalls: [
          { tool: "toee_shopify_read", action: "get_order", ok: true },
          {
            tool: "toee_square_payment_link",
            action: "send_payment_link",
            ok: true,
          },
        ],
      }),
    );
    expect(failures(outcomes).some((o) => o.name.includes("forbidden"))).toBe(
      true,
    );
  });
});

describe("disclosure and text assertions", () => {
  it("checks disclosure flags against harness-reported satisfaction", () => {
    const assertions: ScenarioAssertions = {
      disclosure: { no_account_disclosure: true },
      max_severity: "high",
    };
    expect(
      failures(
        evaluateScenario(
          scenarioWith(assertions),
          turn({ disclosures: { no_account_disclosure: true } }),
        ),
      ),
    ).toHaveLength(0);
    expect(
      failures(evaluateScenario(scenarioWith(assertions), turn())),
    ).toHaveLength(1);
  });

  it("checks must_contain and must_not_contain case-insensitively", () => {
    const assertions: ScenarioAssertions = {
      text: { must_contain: ["order number"], must_not_contain: ["1250"] },
      max_severity: "medium",
    };
    expect(
      failures(
        evaluateScenario(
          scenarioWith(assertions),
          turn({ outboundText: "Please share your ORDER NUMBER." }),
        ),
      ),
    ).toHaveLength(0);
    const bad = failures(
      evaluateScenario(
        scenarioWith(assertions),
        turn({ outboundText: "Your balance is 1250 today." }),
      ),
    );
    // must_contain missing AND must_not_contain present
    expect(bad).toHaveLength(2);
  });
});

describe("memory assertions", () => {
  it("passes expect_upsert and expect_upsert_slot when the slot was upserted", () => {
    const assertions: ScenarioAssertions = {
      memory_assertions: {
        expect_upsert: true,
        expect_upsert_slot: "contact_time_preference",
      },
      max_severity: "high",
    };
    expect(
      failures(
        evaluateScenario(
          scenarioWith(assertions),
          turn({ memoryUpserts: ["contact_time_preference"] }),
        ),
      ),
    ).toHaveLength(0);
    expect(
      failures(evaluateScenario(scenarioWith(assertions), turn())),
    ).toHaveLength(2);
  });

  it("passes forbid_inferred_upsert only when no upsert occurred", () => {
    const assertions: ScenarioAssertions = {
      memory_assertions: { forbid_inferred_upsert: true },
      max_severity: "high",
    };
    expect(
      failures(evaluateScenario(scenarioWith(assertions), turn())),
    ).toHaveLength(0);
    expect(
      failures(
        evaluateScenario(
          scenarioWith(assertions),
          turn({
            toolCalls: [
              {
                tool: "toee_customer_memory",
                action: "upsert_preference",
                ok: true,
              },
            ],
          }),
        ),
      ),
    ).toHaveLength(1);
  });

  it("passes honor_injected_preference only when the harness reports it", () => {
    const assertions: ScenarioAssertions = {
      memory_assertions: { honor_injected_preference: true },
      max_severity: "medium",
    };
    expect(
      failures(
        evaluateScenario(
          scenarioWith(assertions),
          turn({ honoredInjectedPreference: true }),
        ),
      ),
    ).toHaveLength(0);
    expect(
      failures(evaluateScenario(scenarioWith(assertions), turn())),
    ).toHaveLength(1);
  });
});
