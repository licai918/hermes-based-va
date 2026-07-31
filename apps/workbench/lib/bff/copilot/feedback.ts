// Draft feedback BFF for the Copilot Gateway (0.0.4 S07/S09, FR-7/FR-8/FR-9/
// FR-10). POST /api/copilot/feedback discriminates by `kind` (defaulting to
// "rating"): "rating" dispatches toee_feedback.submit_draft_rating (S06) -- a
// rep's thumbs up/down on a copilot draft, requiring draft_text and (on a down
// verdict) at least one INTERNAL reason tag. "outcome" dispatches
// toee_feedback.record_draft_outcome (S08) -- the IMPLICIT sent_as_is/
// sent_edited capture fired fire-and-forget from a successful governed send
// (GovernedSendModal.tsx), sharing the SAME draft_correlation_id the rating
// branch uses so both mechanisms' rows can be joined per draft.
//
// ROLE: this route sits under /api/copilot/ but NOT /api/copilot/audit/, so by
// canAccess's prefix rules (lib/auth/access.ts) it is open to any authenticated
// workbench user -- correct here, since reps are the intended feedback authors
// (unlike review.ts's supervisor/admin-only write beside it). Verified, not
// assumed: lib/auth/access.test.ts asserts canAccess(rep, "/api/copilot/feedback")
// === true, the same way it does for the other non-audit copilot routes. No
// in-handler role gate.
//
// Case-ownership (the acting rep must hold the case) is enforced by the Python
// handler (S06's _require_case_held_by), not re-checked here -- a policy_blocked
// denial maps to 403 via hermesErrorToProblem, same as every other governed write.
import { INTERNAL_REVIEW_REASON_TAGS } from "@toee/shared";
import { json, problem } from "../respond";
import { readJsonBody } from "./deps";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { mapDraftRating } from "../../gateway/hermes-map";
import type {
  DraftKind,
  DraftOutcome,
  DraftRatingVerdict,
  InternalReviewReasonTag,
} from "../../gateway/types";

const DRAFT_KINDS: readonly DraftKind[] = ["sms", "email", "note"];

function readNonEmpty(body: Record<string, unknown> | null, key: string): string | null {
  const value = body?.[key];
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function readDraftKind(body: Record<string, unknown> | null): DraftKind | null {
  const value = body?.draft_kind;
  return (DRAFT_KINDS as readonly unknown[]).includes(value)
    ? (value as DraftKind)
    : null;
}

function readVerdict(body: Record<string, unknown> | null): DraftRatingVerdict | null {
  const value = body?.verdict;
  return value === "up" || value === "down" ? value : null;
}

// null means "reject the request"; a well-formed absent/empty list reads as [].
function readReasonTags(
  body: Record<string, unknown> | null,
): InternalReviewReasonTag[] | null {
  const raw = body?.reason_tags;
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw)) return null;
  const valid = raw.every(
    (t) =>
      typeof t === "string" &&
      (INTERNAL_REVIEW_REASON_TAGS as readonly string[]).includes(t),
  );
  return valid ? (raw as InternalReviewReasonTag[]) : null;
}

// undefined = absent (fine), null = present but the wrong type (reject).
function readComment(body: Record<string, unknown> | null): string | undefined | null {
  const value = body?.comment;
  if (value === undefined || value === null) return undefined;
  return typeof value === "string" ? value : null;
}

async function handleDraftRating(
  body: Record<string, unknown> | null,
  client: HermesApiClient,
): Promise<Response> {
  const caseId = readNonEmpty(body, "case_id");
  if (!caseId) return problem(400, "case_id is required");

  const draftCorrelationId = readNonEmpty(body, "draft_correlation_id");
  if (!draftCorrelationId) return problem(400, "draft_correlation_id is required");

  const draftKind = readDraftKind(body);
  if (!draftKind) {
    return problem(400, `draft_kind must be one of ${DRAFT_KINDS.join(", ")}`);
  }

  const draftText = readNonEmpty(body, "draft_text");
  if (!draftText) return problem(400, "draft_text is required");

  const verdict = readVerdict(body);
  if (!verdict) return problem(400, 'verdict must be "up" or "down"');

  const reasonTags = readReasonTags(body);
  if (reasonTags === null) {
    return problem(
      400,
      `reason_tags must only contain values from ${INTERNAL_REVIEW_REASON_TAGS.join(", ")}`,
    );
  }
  if (verdict === "down" && reasonTags.length === 0) {
    return problem(400, "a down verdict requires at least one reason tag");
  }

  const comment = readComment(body);
  if (comment === null) return problem(400, "comment must be a string");

  try {
    const result = await client.dispatchWrite("toee_feedback", "submit_draft_rating", {
      case_id: caseId,
      draft_correlation_id: draftCorrelationId,
      draft_kind: draftKind,
      draft_text: draftText,
      verdict,
      reason_tags: reasonTags,
      ...(comment !== undefined ? { comment } : {}),
    });
    return json({ rating: mapDraftRating(result) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// record_draft_outcome (S08's write path; S09 wires it up here) -- the
// IMPLICIT counterpart to a rating: did the rep send the generated draft
// untouched or edit it first. Same required trio as the rating branch
// (case_id, draft_correlation_id, draft_kind, draft_text) plus outcome +
// edit_distance_ratio, which is required exactly when outcome is
// "sent_edited" and rejected outright otherwise -- mirrors the Python
// driver's own "reject, don't coerce" validation
// (hermes/toee_hermes/drivers/mock/feedback.py's _read_edit_distance_ratio)
// so a malformed request 400s here instead of round-tripping to a 502.
const DRAFT_OUTCOMES: readonly DraftOutcome[] = ["sent_as_is", "sent_edited"];

function readOutcome(body: Record<string, unknown> | null): DraftOutcome | null {
  const value = body?.outcome;
  return (DRAFT_OUTCOMES as readonly unknown[]).includes(value)
    ? (value as DraftOutcome)
    : null;
}

// null means "reject the request"; undefined means "absent, and that's fine
// for this outcome"; a number is the validated ratio for a sent_edited row.
function readEditDistanceRatio(
  body: Record<string, unknown> | null,
  outcome: DraftOutcome,
): number | undefined | null {
  const raw = body?.edit_distance_ratio;
  if (outcome === "sent_edited") {
    return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
  }
  return raw === undefined || raw === null ? undefined : null;
}

// 0.0.5 S27 (FR-33, D11): the text the rep ACTUALLY sent, which is the second
// operand edit-diff mining span-diffs `draft_text` against. Same tri-state
// convention as readEditDistanceRatio above -- null rejects the request,
// undefined means "absent, and that is fine".
//
// OPTIONAL on a sent_edited outcome, deliberately: this POST is fire-and-forget
// from a send the customer has already received, so a caller that predates the
// column must still be able to record its outcome. Those rows are simply
// invisible to mining, which is D11's no-backfill position stated as behaviour.
// REJECTED on sent_as_is: "nothing was edited" and "here is the result of the
// edit" cannot both be true.
function readSentText(
  body: Record<string, unknown> | null,
  outcome: DraftOutcome,
): string | undefined | null {
  const raw = body?.sent_text;
  if (raw === undefined || raw === null) return undefined;
  if (outcome !== "sent_edited") return null;
  return typeof raw === "string" && raw.trim().length > 0 ? raw : null;
}

async function handleDraftOutcome(
  body: Record<string, unknown> | null,
  client: HermesApiClient,
): Promise<Response> {
  const caseId = readNonEmpty(body, "case_id");
  if (!caseId) return problem(400, "case_id is required");

  const draftCorrelationId = readNonEmpty(body, "draft_correlation_id");
  if (!draftCorrelationId) return problem(400, "draft_correlation_id is required");

  const draftKind = readDraftKind(body);
  if (!draftKind) {
    return problem(400, `draft_kind must be one of ${DRAFT_KINDS.join(", ")}`);
  }

  const draftText = readNonEmpty(body, "draft_text");
  if (!draftText) return problem(400, "draft_text is required");

  const outcome = readOutcome(body);
  if (!outcome) {
    return problem(400, `outcome must be one of ${DRAFT_OUTCOMES.join(", ")}`);
  }

  const editDistanceRatio = readEditDistanceRatio(body, outcome);
  if (editDistanceRatio === null) {
    return problem(
      400,
      outcome === "sent_edited"
        ? "sent_edited requires a numeric edit_distance_ratio"
        : "sent_as_is must not include edit_distance_ratio",
    );
  }

  const sentText = readSentText(body, outcome);
  if (sentText === null) {
    return problem(
      400,
      outcome === "sent_edited"
        ? "sent_text must be a non-empty string when provided"
        : "sent_as_is must not include sent_text",
    );
  }

  try {
    await client.dispatchWrite("toee_feedback", "record_draft_outcome", {
      case_id: caseId,
      draft_correlation_id: draftCorrelationId,
      draft_kind: draftKind,
      draft_text: draftText,
      outcome,
      ...(editDistanceRatio !== undefined ? { edit_distance_ratio: editDistanceRatio } : {}),
      ...(sentText !== undefined ? { sent_text: sentText } : {}),
    });
    // ponytail: no response mapper -- the caller fires this and forgets (S09),
    // and the ratio has no consumer yet (Phase 2). Add mapDraftOutcome the day
    // something reads this response body.
    return json({ recorded: true });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleSubmitDraftFeedbackViaApi(
  req: Request,
  client: HermesApiClient,
): Promise<Response> {
  const body = await readJsonBody(req);
  const kind = body?.kind ?? "rating";
  switch (kind) {
    case "rating":
      return handleDraftRating(body, client);
    case "outcome":
      return handleDraftOutcome(body, client);
    default:
      return problem(400, `unknown feedback kind: ${String(kind)}`);
  }
}
