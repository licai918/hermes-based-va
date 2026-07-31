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

describe("toee_feedback action enum (ADR-0154)", () => {
  // NOT a parity check, despite what this used to be called. It compares the
  // catalog against a hardcoded copy of itself, so it can only catch someone
  // editing tools.ts without editing this file -- it cannot see the Python
  // catalog and never could. What it IS good for is pinning the exact ORDER and
  // membership ADR-0154 specifies, which the cross-language check deliberately
  // does not (that one compares sets, because ordering is a formatting concern).
  //
  // The real drift check is hermes/tests/test_tool_catalog_parity.py, which
  // reads this file and fails the build when the two catalogs disagree.
  it("pins the four actions ADR-0154 specifies, in order", () => {
    expect(TOOL_CATALOG.toee_feedback).toEqual([
      "submit_interaction_review",
      "record_draft_outcome",
      "submit_draft_rating",
      "list_feedback",
    ]);
  });
});
