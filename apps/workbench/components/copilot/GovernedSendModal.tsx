"use client";

// Governed SMS send confirmation (ADR-0083). The two-step send flow ends
// here: the employee confirms the exact outbound body, the acting account, and
// the case before the governed BFF send fires. On success we close and let the
// container refetch the thread (onSent); on failure we surface the server message
// through the global error banner and keep the modal open — nothing is fabricated.
//
// 0.0.4 S09 (FR-7/FR-9): on a SUCCESSFUL send only, also capture whether the
// rep sent the draft as generated or edited it first -- zero rep effort, zero
// risk to the customer reply. `originalBody` is the draft AS GENERATED
// (CopilotGateway keeps this separate from the editable working copy, since
// editing mutates `body` in place); comparing the two after trimming gives
// sent_as_is or sent_edited + an edit-distance ratio. The outcome POST is
// FIRE-AND-FORGET -- same discipline as hermes-runtime's emit_metric_event:
// any failure is caught, logged, and swallowed. It is never awaited before
// onSent()/onClose(), so it can never delay the modal closing or turn a
// successful send into a visible error.
import { useState } from "react";
import { ApiError } from "@/lib/api/http";
import {
  recordDraftOutcome,
  sendSms,
  type DraftKind,
  type DraftOutcome,
} from "@/lib/api/copilot-client";
import { useErrorBanner } from "@/components/shell/error-banner";

const META: React.CSSProperties = { fontSize: "0.78rem", color: "#555" };

// ponytail: classic O(len(a)*len(b)) Levenshtein DP -- fine for SMS/email/note
// length drafts, not for arbitrarily large text. Ratio is distance normalized
// by the longer string's length (0 = identical, 1 = completely different).
function levenshteinDistance(a: string, b: string): number {
  if (a === b) return 0;
  const m = a.length;
  const n = b.length;
  if (m === 0) return n;
  if (n === 0) return m;
  let prev: number[] = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const curr: number[] = new Array(n + 1).fill(0);
    curr[0] = i;
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      curr[j] = Math.min(
        (prev[j] ?? 0) + 1,
        (curr[j - 1] ?? 0) + 1,
        (prev[j - 1] ?? 0) + cost,
      );
    }
    prev = curr;
  }
  return prev[n] ?? 0;
}

function editDistanceRatio(original: string, sent: string): number {
  const maxLen = Math.max(original.length, sent.length);
  if (maxLen === 0) return 0;
  return levenshteinDistance(original, sent) / maxLen;
}

export function GovernedSendModal({
  caseId,
  body,
  accountId,
  identitySummary,
  originalBody,
  draftCorrelationId,
  draftKind,
  onSent,
  onClose,
  send = sendSms,
  recordOutcome = recordDraftOutcome,
}: {
  caseId: string;
  body: string;
  accountId?: string;
  identitySummary?: string;
  // The draft AS GENERATED, before any rep edits (0.0.4 S09). Outcome capture
  // is skipped entirely (no network call at all) unless this, draftCorrelationId,
  // and draftKind are all supplied -- callers that don't wire these up (e.g.
  // older tests) get exactly the old send-only behaviour.
  originalBody?: string;
  draftCorrelationId?: string | null;
  draftKind?: DraftKind | null;
  onSent: () => void;
  onClose: () => void;
  send?: (caseId: string, body: string) => Promise<unknown>;
  recordOutcome?: (input: {
    caseId: string;
    draftCorrelationId: string;
    draftKind: DraftKind;
    draftText: string;
    outcome: DraftOutcome;
    editDistanceRatio?: number;
  }) => Promise<unknown>;
}) {
  const { showError } = useErrorBanner();
  const [busy, setBusy] = useState(false);

  // Fire-and-forget: intentionally not awaited by confirm() below, and it must
  // NEVER throw at its caller -- the send has already succeeded by the time
  // this runs, so anything escaping here would report a false send failure to
  // the rep (and invite a retry that double-sends to the customer).
  //
  // Two escape routes, both closed: the `.catch()` handles an async rejection,
  // and the surrounding try/catch handles a SYNCHRONOUS throw -- from a
  // non-async `recordOutcome` (it is an injectable prop, so its shape is not
  // ours to assume) or from the ratio computation in the argument list. The
  // guarantee lives here rather than at the call site so every future caller
  // inherits it.
  function captureSendOutcome(sentBody: string) {
    try {
      if (!draftCorrelationId || !draftKind || originalBody === undefined) return;
      const trimmedOriginal = originalBody.trim();
      const trimmedSent = sentBody.trim();
      const outcome: DraftOutcome =
        trimmedOriginal === trimmedSent ? "sent_as_is" : "sent_edited";
      recordOutcome({
        caseId,
        draftCorrelationId,
        draftKind,
        draftText: originalBody,
        outcome,
        ...(outcome === "sent_edited"
          ? { editDistanceRatio: editDistanceRatio(trimmedOriginal, trimmedSent) }
          : {}),
      }).catch((err) => {
        // eslint-disable-next-line no-console
        console.error("record_draft_outcome failed (swallowed, non-fatal)", err);
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("record_draft_outcome threw (swallowed, non-fatal)", err);
    }
  }

  async function confirm() {
    setBusy(true);
    try {
      await send(caseId, body);
      captureSendOutcome(body);
      onSent();
      onClose();
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Failed to send SMS message";
      showError(message, err instanceof ApiError ? `HTTP ${err.status}` : undefined);
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Confirm SMS send"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: "1.25rem",
          maxWidth: 480,
          width: "90%",
          display: "flex",
          flexDirection: "column",
          gap: "0.75rem",
        }}
      >
        <h2 style={{ margin: 0 }}>Send via SMS</h2>
        <p style={{ margin: 0, color: "#555" }}>
          Confirm this SMS reply. It will be sent to the customer and recorded in the
          case thread and audit log.
        </p>
        <blockquote
          style={{
            margin: 0,
            padding: "0.6rem 0.75rem",
            background: "#f6f6f6",
            borderLeft: "3px solid #1a4fd6",
            whiteSpace: "pre-wrap",
          }}
        >
          {body}
        </blockquote>
        <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "0.2rem 0.6rem" }}>
          <dt style={META}>Case</dt>
          <dd style={{ ...META, margin: 0 }}>{caseId}</dd>
          {identitySummary ? (
            <>
              <dt style={META}>Customer</dt>
              <dd style={{ ...META, margin: 0 }}>{identitySummary}</dd>
            </>
          ) : null}
          {accountId ? (
            <>
              <dt style={META}>Acting account</dt>
              <dd style={{ ...META, margin: 0 }}>{accountId}</dd>
            </>
          ) : null}
        </dl>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" onClick={confirm} disabled={busy}>
            {busy ? "Sending…" : "Confirm send"}
          </button>
        </div>
      </div>
    </div>
  );
}
