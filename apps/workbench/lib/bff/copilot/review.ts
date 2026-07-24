// Interaction Review write for the Copilot BFF (ADR-0094/0141/0154, 0.0.4 S04).
// `POST /api/copilot/audit/review` dispatches toee_feedback.submit_interaction_review
// -- a supervisor/admin's pass/fail judgment on one Auto-Handled Interaction record
// or one sales_outreach Follow-up Case. The audit surfaces stay read-only toward
// conversation data; this is the ONLY write the audit BFF makes, and it targets the
// review table only.
//
// ROLE ENFORCEMENT (quality-feedback S04, verified not assumed): the datastore
// carries no role column, so the Python layer cannot tell a supervisor from a rep.
// The boundary lives at the BFF route PREFIX gate instead -- this route sits under
// /api/copilot/audit/*, which withSession's canAccess already restricts to
// supervisor/admin (lib/auth/access.ts), exactly like the read-only
// get_auto_handled/get_sales_outreach routes beside it. lib/auth/access.test.ts
// pins `canAccess(rep, "/api/copilot/audit/review") === false` so this is proven,
// not assumed. This handler therefore has no in-handler role check (mirrors
// audit.ts's read handlers) -- the actor still rides along automatically via the
// per-profile client `dispatchWrite` builds (ADR-0141), which fails closed with no
// acting account regardless.
//
// Body validation runs here, in TypeScript, BEFORE any dispatch: subject_kind and
// verdict against their closed enums, reason_tags against the EXTERNAL Review
// Reason Tag set (packages/shared/src/feedback.ts, NOT hardcoded here), and a fail
// verdict requiring at least one tag. Validating up front means a malformed
// request 400s directly instead of round-tripping to the Python layer's
// unexpected_error, which hermes-error.ts maps to a blanket 502.
import { EXTERNAL_REVIEW_REASON_TAGS } from "@toee/shared";
import { json, problem } from "../respond";
import { readJsonBody } from "./deps";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { mapInteractionReview } from "../../gateway/hermes-map";
import type {
  ExternalReviewReasonTag,
  InteractionReviewSubjectKind,
} from "../../gateway/types";

const SUBJECT_KINDS: readonly InteractionReviewSubjectKind[] = [
  "auto_handled_record",
  "sales_outreach_case",
];

function readSubjectKind(
  body: Record<string, unknown> | null,
): InteractionReviewSubjectKind | null {
  const value = body?.subject_kind;
  return (SUBJECT_KINDS as readonly unknown[]).includes(value)
    ? (value as InteractionReviewSubjectKind)
    : null;
}

function readSubjectId(body: Record<string, unknown> | null): string | null {
  const value = body?.subject_id;
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function readVerdict(body: Record<string, unknown> | null): "pass" | "fail" | null {
  const value = body?.verdict;
  return value === "pass" || value === "fail" ? value : null;
}

// null means "reject the request"; a well-formed absent/empty list reads as [].
function readReasonTags(
  body: Record<string, unknown> | null,
): ExternalReviewReasonTag[] | null {
  const raw = body?.reason_tags;
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw)) return null;
  const valid = raw.every(
    (t) =>
      typeof t === "string" &&
      (EXTERNAL_REVIEW_REASON_TAGS as readonly string[]).includes(t),
  );
  return valid ? (raw as ExternalReviewReasonTag[]) : null;
}

// undefined = absent (fine), null = present but the wrong type (reject).
function readComment(body: Record<string, unknown> | null): string | undefined | null {
  const value = body?.comment;
  if (value === undefined || value === null) return undefined;
  return typeof value === "string" ? value : null;
}

export async function handleSubmitInteractionReviewViaApi(
  req: Request,
  client: HermesApiClient,
): Promise<Response> {
  const body = await readJsonBody(req);

  const subjectKind = readSubjectKind(body);
  if (!subjectKind) {
    return problem(400, `subject_kind must be one of ${SUBJECT_KINDS.join(", ")}`);
  }
  const subjectId = readSubjectId(body);
  if (!subjectId) return problem(400, "subject_id is required");

  const verdict = readVerdict(body);
  if (!verdict) return problem(400, 'verdict must be "pass" or "fail"');

  const reasonTags = readReasonTags(body);
  if (reasonTags === null) {
    return problem(
      400,
      `reason_tags must only contain values from ${EXTERNAL_REVIEW_REASON_TAGS.join(", ")}`,
    );
  }
  if (verdict === "fail" && reasonTags.length === 0) {
    return problem(400, "a fail verdict requires at least one reason tag");
  }

  const comment = readComment(body);
  if (comment === null) return problem(400, "comment must be a string");

  try {
    const result = await client.dispatchWrite(
      "toee_feedback",
      "submit_interaction_review",
      {
        subject_kind: subjectKind,
        subject_id: subjectId,
        verdict,
        reason_tags: reasonTags,
        ...(comment !== undefined ? { comment } : {}),
      },
    );
    return json({ review: mapInteractionReview(result) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
