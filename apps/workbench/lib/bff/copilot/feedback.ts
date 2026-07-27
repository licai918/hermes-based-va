// Draft feedback BFF for the Copilot Gateway (0.0.4 S07, FR-8/FR-10). POST
// /api/copilot/feedback dispatches toee_feedback.submit_draft_rating (S06) -- a
// rep's thumbs up/down on a copilot draft, requiring draft_text and (on a down
// verdict) at least one INTERNAL reason tag. The body discriminates by `kind`
// (defaulting to "rating" since that's the only kind this slice ships) so
// S09's outcome branch (record_draft_outcome, fired from a successful governed
// send) can land on this SAME route later without reworking this branch.
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

export async function handleSubmitDraftFeedbackViaApi(
  req: Request,
  client: HermesApiClient,
): Promise<Response> {
  const body = await readJsonBody(req);
  const kind = body?.kind ?? "rating";
  switch (kind) {
    case "rating":
      return handleDraftRating(body, client);
    default:
      return problem(400, `unknown feedback kind: ${String(kind)}`);
  }
}
