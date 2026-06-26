"use client";

// Governed Textline send confirmation (ADR-0083). The two-step send flow ends
// here: the employee confirms the exact outbound body, the acting account, and
// the case before the governed BFF send fires. On success we close and let the
// container refetch the thread (onSent); on failure we surface the server message
// through the global error banner and keep the modal open — nothing is fabricated.
import { useState } from "react";
import { ApiError } from "@/lib/api/http";
import { sendTextline } from "@/lib/api/copilot-client";
import { useErrorBanner } from "@/components/shell/error-banner";

const META: React.CSSProperties = { fontSize: "0.78rem", color: "#555" };

export function GovernedSendModal({
  caseId,
  body,
  accountId,
  identitySummary,
  onSent,
  onClose,
  send = sendTextline,
}: {
  caseId: string;
  body: string;
  accountId?: string;
  identitySummary?: string;
  onSent: () => void;
  onClose: () => void;
  send?: (caseId: string, body: string) => Promise<unknown>;
}) {
  const { showError } = useErrorBanner();
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    try {
      await send(caseId, body);
      onSent();
      onClose();
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Failed to send Textline message";
      showError(message, err instanceof ApiError ? `HTTP ${err.status}` : undefined);
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Confirm Textline send"
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
        <h2 style={{ margin: 0 }}>Send via Textline</h2>
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
