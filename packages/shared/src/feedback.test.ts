import { describe, it, expect } from "vitest";
import {
  EXTERNAL_REVIEW_REASON_TAGS,
  INTERNAL_REVIEW_REASON_TAGS,
} from "./feedback";
import { TOOL_CATALOG } from "./tools";

describe("Review Reason Tag enums (ADR-0154)", () => {
  it("EXTERNAL matches the Python authoritative copy (schemas.py)", () => {
    expect(EXTERNAL_REVIEW_REASON_TAGS).toEqual([
      "factual_error",
      "tone_inappropriate",
      "policy_violation",
      "tool_misuse",
      "missed_information",
      "should_have_escalated",
      "other",
    ]);
  });

  it("INTERNAL matches the Python authoritative copy (schemas.py)", () => {
    expect(INTERNAL_REVIEW_REASON_TAGS).toEqual([
      "factual_error",
      "wrong_tone",
      "missing_context",
      "too_verbose",
      "wrong_action",
      "other",
    ]);
  });

  it("the two sets are deliberately separate", () => {
    const external = new Set<string>(EXTERNAL_REVIEW_REASON_TAGS);
    const internal = new Set<string>(INTERNAL_REVIEW_REASON_TAGS);
    // Only "other" and "factual_error" are shared by coincidence of naming;
    // every other tag differs, proving these are two distinct enums, not one
    // set reused under two names.
    const onlyExternal = [...external].filter((tag) => !internal.has(tag));
    const onlyInternal = [...internal].filter((tag) => !external.has(tag));
    expect(onlyExternal.length).toBeGreaterThan(0);
    expect(onlyInternal.length).toBeGreaterThan(0);
  });
});

describe("toee_feedback catalog parity (S02)", () => {
  it("TS action enum matches the Python TOOL_CATALOG exactly", () => {
    // The Python side of this parity check lives in
    // hermes/tests/test_tool_catalog.py::test_feedback_actions_match_adr_0154.
    expect(TOOL_CATALOG.toee_feedback).toEqual([
      "submit_interaction_review",
      "record_draft_outcome",
      "submit_draft_rating",
      "list_feedback",
    ]);
  });
});
