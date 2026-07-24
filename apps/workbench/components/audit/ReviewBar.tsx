"use client";

// Review bar (ADR-0154, 0.0.4 S04): mounted below the summary header on both audit
// detail views. Pass is one click; Fail expands the EXTERNAL Review Reason Tag
// chips (packages/shared/src/feedback.ts -- never hardcoded here) plus an optional
// comment. Visible to supervisor/admin only -- reps never see review controls
// (the datastore carries no role column, so this is presentational; the real
// enforcement is the BFF route-prefix gate, see lib/bff/copilot/review.ts). An
// existing review from THIS session renders its verdict/tags with an edit
// affordance; re-submitting appends a new row (the backend is append-only), it
// never overwrites the prior one.
import { useState } from "react";
import {
  EXTERNAL_REVIEW_REASON_TAGS,
  WORKBENCH_ROLES,
  type ExternalReviewReasonTag,
  type InteractionReviewVerdict,
  type WorkbenchRoleId,
} from "@toee/shared";
import { submitInteractionReview } from "@/lib/api/audit-client";
import type { InteractionReviewSubjectKind } from "@/lib/gateway/types";
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
};

export function ReviewBar({
  role,
  subjectKind,
  subjectId,
  submit = (input) => submitInteractionReview(input),
}: {
  role?: WorkbenchRoleId;
  subjectKind: InteractionReviewSubjectKind;
  subjectId: string;
  submit?: (input: SubmitReviewInput) => Promise<unknown>;
}) {
  const [myReview, setMyReview] = useState<MyReview | null>(null);
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
      setMyReview({ verdict, reasonTags });
      setEditing(false);
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit review");
    } finally {
      setBusy(false);
    }
  }

  if (myReview && !editing) {
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
        <button type="button" onClick={() => setEditing(true)}>
          Edit review
        </button>
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
