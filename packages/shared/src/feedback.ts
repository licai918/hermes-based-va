// The two Review Reason Tag enums (ADR-0154, 0.0.4 S02). EXTERNAL is used by
// toee_feedback.submit_interaction_review (supervisor/admin pass/fail review
// of an auto_handled_record or sales_outreach_case); INTERNAL is used by
// toee_feedback.submit_draft_rating (a rep's thumbs up/down on a copilot
// draft). The sets are deliberately separate -- an external tag on an
// internal rating (or vice versa) is a validation error the S03/S06 handlers
// enforce. Python keeps its own authoritative copy at
// hermes/toee_hermes/plugin/schemas.py -- update both lists together so the
// two runtimes can't silently drift.
export type ExternalReviewReasonTag =
  | "factual_error"
  | "tone_inappropriate"
  | "policy_violation"
  | "tool_misuse"
  | "missed_information"
  | "should_have_escalated"
  | "other";

export const EXTERNAL_REVIEW_REASON_TAGS: readonly ExternalReviewReasonTag[] =
  [
    "factual_error",
    "tone_inappropriate",
    "policy_violation",
    "tool_misuse",
    "missed_information",
    "should_have_escalated",
    "other",
  ];

export type InternalReviewReasonTag =
  | "factual_error"
  | "wrong_tone"
  | "missing_context"
  | "too_verbose"
  | "wrong_action"
  | "other";

export const INTERNAL_REVIEW_REASON_TAGS: readonly InternalReviewReasonTag[] =
  [
    "factual_error",
    "wrong_tone",
    "missing_context",
    "too_verbose",
    "wrong_action",
    "other",
  ];

// toee_feedback.submit_interaction_review's verdict (external mechanism).
export type InteractionReviewVerdict = "pass" | "fail";

// toee_feedback.submit_draft_rating's verdict (internal mechanism).
export type DraftRatingVerdict = "up" | "down";

// toee_feedback.record_draft_outcome's implicit outcome (internal mechanism).
export type DraftOutcome = "sent_as_is" | "sent_edited";
