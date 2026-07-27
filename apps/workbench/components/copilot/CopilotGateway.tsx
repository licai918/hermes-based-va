"use client";

// Copilot Gateway (ADR-0081 interaction states, ADR-0083 governed send). With no
// selected case it shows the idle "needs case" prompt and no drafting. With a
// case it offers chat + Copilot Draft Actions; a returned draft becomes an
// editable draft card. The governed "Send via SMS" affordance only appears
// for an SMS case with an active session that the operator holds, and routes
// through the confirmation modal. Network lives in injected chat/draft callbacks
// so this stays presentational and unit-testable.
import { useState } from "react";
import { INTERNAL_REVIEW_REASON_TAGS } from "@toee/shared";
import { submitDraftFeedback, type ChatResponse, type DraftKind } from "@/lib/api/copilot-client";
import type { DraftRatingVerdict, InternalReviewReasonTag } from "@/lib/gateway/types";
import type { WorkbenchCase } from "@/lib/gateway/types";
import { ApiError } from "@/lib/api/http";
import { useErrorBanner } from "@/components/shell/error-banner";
import { GovernedSendModal } from "./GovernedSendModal";

const RATING_TAG_LABELS: Record<InternalReviewReasonTag, string> = {
  factual_error: "Factual error",
  wrong_tone: "Wrong tone",
  missing_context: "Missing context",
  too_verbose: "Too verbose",
  wrong_action: "Wrong action",
  other: "Other",
};

// Thumbs rating on the draft card (0.0.4 S07, FR-8/FR-10). Up submits
// immediately; down expands the INTERNAL reason-tag chips (never the external
// set) plus an optional comment. This is an ADJACENT control: it keeps its own
// busy/error state entirely separate from the draft/send flow, so a failed
// rating never touches draftBody, never disables Send, and never opens the
// global error banner -- it renders its own inline alert instead.
function DraftRatingControls({
  onRate,
}: {
  onRate: (
    verdict: DraftRatingVerdict,
    reasonTags: InternalReviewReasonTag[],
    comment: string,
  ) => Promise<unknown>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [tags, setTags] = useState<InternalReviewReasonTag[]>([]);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleTag(tag: InternalReviewReasonTag) {
    setTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  }

  function reset() {
    setExpanded(false);
    setTags([]);
    setComment("");
    setError(null);
  }

  async function submit(verdict: DraftRatingVerdict, reasonTags: InternalReviewReasonTag[]) {
    setBusy(true);
    setError(null);
    try {
      await onRate(verdict, reasonTags, comment);
      reset();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit rating");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", alignItems: "flex-end" }}>
      {error ? (
        <span role="alert" style={{ fontSize: "0.7rem", color: "#b00020" }}>
          {error}
        </span>
      ) : null}
      {!expanded ? (
        <div style={{ display: "flex", gap: "0.3rem" }}>
          <button
            type="button"
            aria-label="Thumbs up"
            disabled={busy}
            onClick={() => submit("up", [])}
          >
            👍
          </button>
          <button
            type="button"
            aria-label="Thumbs down"
            disabled={busy}
            onClick={() => setExpanded(true)}
          >
            👎
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", alignItems: "flex-end" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", justifyContent: "flex-end" }}>
            {INTERNAL_REVIEW_REASON_TAGS.map((tag) => (
              <button
                key={tag}
                type="button"
                aria-pressed={tags.includes(tag)}
                onClick={() => toggleTag(tag)}
                style={{ fontWeight: tags.includes(tag) ? 700 : 400, fontSize: "0.7rem" }}
              >
                {RATING_TAG_LABELS[tag]}
              </button>
            ))}
          </div>
          <textarea
            aria-label="Rating comment"
            placeholder="Optional comment"
            value={comment}
            rows={1}
            onChange={(e) => setComment(e.target.value)}
            style={{ font: "inherit", width: "100%" }}
          />
          <div style={{ display: "flex", gap: "0.3rem" }}>
            <button type="button" disabled={busy} onClick={reset}>
              Cancel
            </button>
            <button
              type="button"
              disabled={busy || tags.length === 0}
              onClick={() => submit("down", tags)}
            >
              Submit rating
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Phase-1 SMS send gate (ADR-0083): SMS case, active SMS session, held by
// the signed-in operator.
export function canSendViaSms(
  workbenchCase: WorkbenchCase | null,
  accountId: string,
): boolean {
  return (
    workbenchCase !== null &&
    workbenchCase.channel === "sms" &&
    workbenchCase.smsSessionActive === true &&
    workbenchCase.assigneeAccountId === accountId
  );
}

type Turn = { author: "you" | "copilot"; text: string };

const DRAFT_KINDS: { kind: DraftKind; label: string }[] = [
  { kind: "sms", label: "Draft SMS" },
  { kind: "email", label: "Draft Email" },
  { kind: "note", label: "Draft Note" },
];

const PANEL: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.6rem",
  padding: "0.75rem",
  minHeight: 0,
};

export function CopilotGateway({
  case: workbenchCase,
  accountId,
  chat,
  draft,
  onSent,
  rateDraft = submitDraftFeedback,
}: {
  case: WorkbenchCase | null;
  accountId: string;
  chat: (message: string) => Promise<ChatResponse>;
  draft: (kind: DraftKind) => Promise<string>;
  onSent: () => void;
  rateDraft?: (input: {
    caseId: string;
    draftCorrelationId: string;
    draftKind: DraftKind;
    draftText: string;
    verdict: DraftRatingVerdict;
    reasonTags?: InternalReviewReasonTag[];
    comment?: string;
  }) => Promise<unknown>;
}) {
  const { showError } = useErrorBanner();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [draftBody, setDraftBody] = useState<string | null>(null);
  // The draft kind + a client-minted correlation id travel alongside the draft
  // body, set together at both places a draft is produced below. S09 will share
  // this same id with the implicit send-outcome row for the same draft.
  const [draftKind, setDraftKind] = useState<DraftKind | null>(null);
  const [draftCorrelationId, setDraftCorrelationId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  function reportError(err: unknown, fallback: string) {
    const message = err instanceof ApiError ? err.message : fallback;
    showError(message, err instanceof ApiError ? `HTTP ${err.status}` : undefined);
  }

  if (workbenchCase === null) {
    return (
      <section aria-label="Copilot Gateway" style={PANEL}>
        <h2 style={{ margin: 0 }}>Copilot Gateway</h2>
        <p style={{ color: "#666" }}>
          Select a Human Intervention Case from the queue to begin.
        </p>
      </section>
    );
  }

  const caseId = workbenchCase.caseId;
  const eligible = canSendViaSms(workbenchCase, accountId);

  async function handleSend() {
    const message = input.trim();
    if (message.length === 0 || busy) return;
    setBusy(true);
    setTurns((t) => [...t, { author: "you", text: message }]);
    setInput("");
    try {
      const res = await chat(message);
      setTurns((t) => [...t, { author: "copilot", text: res.reply }]);
      if (res.draftCard) {
        setDraftBody(res.draftCard.body);
        setDraftKind(res.draftCard.channel);
        setDraftCorrelationId(globalThis.crypto.randomUUID());
      }
    } catch (err) {
      reportError(err, "Copilot chat failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleDraft(kind: DraftKind) {
    if (busy) return;
    setBusy(true);
    try {
      setDraftBody(await draft(kind));
      setDraftKind(kind);
      setDraftCorrelationId(globalThis.crypto.randomUUID());
    } catch (err) {
      reportError(err, "Draft generation failed");
    } finally {
      setBusy(false);
    }
  }

  function handleSent() {
    setDraftBody(null);
    setDraftKind(null);
    setDraftCorrelationId(null);
    setModalOpen(false);
    onSent();
  }

  // Rating never blocks drafting or sending: DraftRatingControls keeps its own
  // busy/error state and never touches draftBody, so a failed rateDraft call
  // leaves the draft exactly as editable and sendable as before the click.
  async function handleRateDraft(
    verdict: DraftRatingVerdict,
    reasonTags: InternalReviewReasonTag[],
    comment: string,
  ) {
    if (draftBody === null || draftKind === null || draftCorrelationId === null) return;
    await rateDraft({
      caseId,
      draftCorrelationId,
      draftKind,
      draftText: draftBody,
      verdict,
      reasonTags,
      comment: comment.trim() || undefined,
    });
  }

  return (
    <section aria-label="Copilot Gateway" style={PANEL}>
      <h2 style={{ margin: 0 }}>Copilot Gateway</h2>

      <ol
        aria-label="Gateway conversation"
        style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.4rem", overflowY: "auto" }}
      >
        {turns.map((turn, i) => (
          <li
            key={i}
            style={{
              alignSelf: turn.author === "you" ? "flex-end" : "flex-start",
              maxWidth: "85%",
              padding: "0.4rem 0.6rem",
              borderRadius: 8,
              background: turn.author === "you" ? "#1a4fd6" : "#f0f0f0",
              color: turn.author === "you" ? "#fff" : "#222",
              fontSize: "0.85rem",
              whiteSpace: "pre-wrap",
            }}
          >
            {turn.text}
          </li>
        ))}
      </ol>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
        {DRAFT_KINDS.map((d) => (
          <button key={d.kind} type="button" disabled={busy} onClick={() => handleDraft(d.kind)}>
            {d.label}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: "0.4rem", alignItems: "flex-end" }}>
        <textarea
          aria-label="Message Copilot"
          value={input}
          rows={2}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask Copilot about this case…"
          style={{ flex: 1, resize: "vertical", font: "inherit" }}
        />
        <button type="button" onClick={handleSend} disabled={busy}>
          Send
        </button>
      </div>

      {draftBody !== null ? (
        <div
          style={{
            border: "1px solid #d6d6d6",
            borderRadius: 8,
            padding: "0.6rem",
            display: "flex",
            flexDirection: "column",
            gap: "0.4rem",
            background: "#fcfcff",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <strong style={{ fontSize: "0.8rem" }}>Draft</strong>
            <DraftRatingControls onRate={handleRateDraft} />
          </div>
          <textarea
            aria-label="Draft message"
            value={draftBody}
            rows={3}
            onChange={(e) => setDraftBody(e.target.value)}
            style={{ resize: "vertical", font: "inherit" }}
          />
          {eligible ? (
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button type="button" onClick={() => setModalOpen(true)}>
                Send via SMS
              </button>
            </div>
          ) : (
            <span style={{ fontSize: "0.72rem", color: "#888" }}>
              Copy this draft to send manually — governed SMS send is available
              only on an active SMS case you hold.
            </span>
          )}
        </div>
      ) : null}

      {modalOpen && draftBody !== null ? (
        <GovernedSendModal
          caseId={caseId}
          body={draftBody}
          accountId={accountId}
          identitySummary={workbenchCase.identitySummary}
          onSent={handleSent}
          onClose={() => setModalOpen(false)}
        />
      ) : null}
    </section>
  );
}
