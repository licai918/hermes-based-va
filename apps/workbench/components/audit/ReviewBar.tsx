"use client";

// Review bar (ADR-0154, 0.0.4 S04): mounted below the summary header on both audit
// detail views. Pass is one click; Fail expands the EXTERNAL Review Reason Tag
// chips (packages/shared/src/feedback.ts -- never hardcoded here) plus an optional
// comment. Visible to supervisor/admin only -- reps never see review controls;
// hiding the controls here is presentational, the real enforcement is two-layer
// (BFF route-prefix gate, lib/bff/copilot/review.ts, PLUS the Postgres handler's
// own role check against workbench_account.role). An existing review renders its
// verdict/tags/comment with an edit affordance -- seeded from `initialReview`
// (US-7/FR-5: the caller's own latest review, fetched with the record) and kept
// current across a same-session submit; re-submitting appends a new row (the
// backend is append-only), it never overwrites the prior one.
import { useState } from "react";
import {
  EXTERNAL_REVIEW_REASON_TAGS,
  ROUTES,
  WORKBENCH_ROLES,
  type ExternalReviewReasonTag,
  type InteractionReviewVerdict,
  type WorkbenchRoleId,
} from "@toee/shared";
import { submitInteractionReview } from "@/lib/api/audit-client";
import type {
  InteractionReviewSubjectKind,
  MemoryPreferenceSlot,
} from "@/lib/gateway/types";
import { cardStyle, failureStyle, mutedStyle } from "./shared";

const TAG_LABELS: Record<ExternalReviewReasonTag, string> = {
  factual_error: "Factual error",
  tone_inappropriate: "Tone inappropriate",
  policy_violation: "Policy violation",
  tool_misuse: "Tool misuse",
  missed_information: "Missed information",
  should_have_escalated: "Should have escalated",
  other: "Other",
};

function isSupervisorOrAdmin(role?: WorkbenchRoleId): boolean {
  return role === WORKBENCH_ROLES.supervisor || role === WORKBENCH_ROLES.admin;
}

// 0.0.5 S17 (FR-25/US12): which fail reasons are actually preference-shaped.
//
// ONE of the seven, and the narrowness is the point. `tone_inappropriate` says
// the agent's manner was wrong for THIS customer, which is what
// `communication_style_note` is for. The others are not preference-shaped and
// offering a memory correction for them would be an invitation to write a
// customer preference that says nothing about the customer:
// `policy_violation`/`tool_misuse`/`should_have_escalated` are about the agent's
// behaviour, `factual_error` is L5/L7 (D23 routes its halves elsewhere), `other`
// means whatever the comment says, and `missed_information` is an L4 injection
// MISS -- the memory was there and went unused, so correcting the slot fixes
// nothing (D23 records that it has no legal destination yet).
//
// The slot is a SUGGESTION either way: the console the link opens lets the
// supervisor pick any of the four.
export const PREFERENCE_SHAPED_TAGS: Partial<
  Record<ExternalReviewReasonTag, MemoryPreferenceSlot>
> = {
  tone_inappropriate: "communication_style_note",
};

// L4 caps a slot value at 200 chars (MEMORY_VALUE_MAX_LENGTH, enforced by both
// Hermes twins). A comment longer than that is truncated HERE rather than sent
// and rejected -- the supervisor edits the value before confirming anyway, and
// a prefill that cannot be saved is worse than a short one.
const SLOT_VALUE_MAX = 200;

/**
 * The one-click deep link from a failed review to a prefilled L4 correction.
 *
 * Returns null when nothing about this review is preference-shaped, which is
 * most of them. `case` is present only when the subject IS a case: an
 * auto-handled record has no case id to bind a customer memory read to, so the
 * link still carries the slot and the suggested value and the console asks for
 * the case — a form that is honest about what it is missing beats a link that
 * silently drops half its prefill.
 */
export function memoryCorrectionHref(review: {
  subjectKind: InteractionReviewSubjectKind;
  subjectId: string;
  reasonTags: ExternalReviewReasonTag[];
  comment?: string | null;
}): string | null {
  const tag = review.reasonTags.find((t) => PREFERENCE_SHAPED_TAGS[t]);
  if (!tag) return null;
  const params = new URLSearchParams({
    slot: PREFERENCE_SHAPED_TAGS[tag] as string,
    tag,
    from: `${review.subjectKind}:${review.subjectId}`,
  });
  if (review.subjectKind === "sales_outreach_case") params.set("case", review.subjectId);
  // The supervisor's own comment is the suggested value: they wrote it, and
  // they read it again in an editable field before it is stored. Absent, the
  // console opens with the slot chosen and the value blank and usable.
  const comment = review.comment?.trim();
  if (comment) params.set("value", comment.slice(0, SLOT_VALUE_MAX));
  return `${ROUTES.adminMemoryAudit}?${params.toString()}`;
}

export type SubmitReviewInput = {
  subjectKind: InteractionReviewSubjectKind;
  subjectId: string;
  verdict: InteractionReviewVerdict;
  reasonTags: ExternalReviewReasonTag[];
  comment?: string;
};

type MyReview = {
  verdict: InteractionReviewVerdict;
  reasonTags: ExternalReviewReasonTag[];
  comment?: string | null;
};

export function ReviewBar({
  role,
  subjectKind,
  subjectId,
  initialReview = null,
  submit = (input) => submitInteractionReview(input),
}: {
  role?: WorkbenchRoleId;
  subjectKind: InteractionReviewSubjectKind;
  subjectId: string;
  // US-7/FR-5: the current account's own latest review of this subject, as
  // read back with the audit detail record -- renders on load so reopening a
  // record shows the prior verdict instead of a blank bar.
  initialReview?: MyReview | null;
  submit?: (input: SubmitReviewInput) => Promise<unknown>;
}) {
  const [myReview, setMyReview] = useState<MyReview | null>(initialReview);
  const [editing, setEditing] = useState(false);
  const [failing, setFailing] = useState(false);
  const [tags, setTags] = useState<ExternalReviewReasonTag[]>([]);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isSupervisorOrAdmin(role)) return null;

  function resetForm() {
    setFailing(false);
    setTags([]);
    setComment("");
    setError(null);
  }

  function toggleTag(tag: ExternalReviewReasonTag) {
    setTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  }

  async function doSubmit(verdict: InteractionReviewVerdict, reasonTags: ExternalReviewReasonTag[]) {
    setBusy(true);
    setError(null);
    try {
      await submit({
        subjectKind,
        subjectId,
        verdict,
        reasonTags,
        comment: comment.trim() || undefined,
      });
      setMyReview({ verdict, reasonTags, comment: comment.trim() || undefined });
      setEditing(false);
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit review");
    } finally {
      setBusy(false);
    }
  }

  if (myReview && !editing) {
    // FR-25/US12: a failed review with a preference-shaped cause offers the
    // one-click prefilled L4 correction. It is a LINK, not an action — the
    // correction itself is a governed write the supervisor makes on the next
    // screen, with the suggested value in front of them and editable.
    const correctionHref =
      myReview.verdict === "fail"
        ? memoryCorrectionHref({
            subjectKind,
            subjectId,
            reasonTags: myReview.reasonTags,
            comment: myReview.comment,
          })
        : null;
    return (
      <section style={cardStyle} aria-label="Review">
        <p style={{ margin: 0 }}>
          Reviewed:{" "}
          <strong>{myReview.verdict === "pass" ? "Pass" : "Fail"}</strong>
          {myReview.reasonTags.length > 0 && (
            <span style={mutedStyle}>
              {" "}
              ({myReview.reasonTags.map((t) => TAG_LABELS[t]).join(", ")})
            </span>
          )}
        </p>
        {myReview.comment && <p style={mutedStyle}>{myReview.comment}</p>}
        <button type="button" onClick={() => setEditing(true)}>
          Edit review
        </button>
        {correctionHref && (
          <p style={{ margin: "0.5rem 0 0" }}>
            <a href={correctionHref}>Correct this customer&rsquo;s preference</a>
            <span style={mutedStyle}>
              {" "}
              — opens the memory audit with the slot and your comment filled in;
              nothing is written until you confirm there.
            </span>
          </p>
        )}
      </section>
    );
  }

  return (
    <section style={cardStyle} aria-label="Review">
      {error && (
        <p role="alert" style={failureStyle}>
          {error}
        </p>
      )}
      {!failing ? (
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button type="button" disabled={busy} onClick={() => doSubmit("pass", [])}>
            Pass
          </button>
          <button type="button" disabled={busy} onClick={() => setFailing(true)}>
            Fail
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {EXTERNAL_REVIEW_REASON_TAGS.map((tag) => (
              <button
                key={tag}
                type="button"
                aria-pressed={tags.includes(tag)}
                onClick={() => toggleTag(tag)}
                style={{ fontWeight: tags.includes(tag) ? 700 : 400 }}
              >
                {TAG_LABELS[tag]}
              </button>
            ))}
          </div>
          <textarea
            aria-label="Comment"
            placeholder="Optional comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button type="button" disabled={busy} onClick={resetForm}>
              Cancel
            </button>
            <button
              type="button"
              disabled={busy || tags.length === 0}
              onClick={() => doSubmit("fail", tags)}
            >
              Submit fail
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
