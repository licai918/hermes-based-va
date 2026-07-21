"use client";

// Copilot Gateway (ADR-0081 interaction states, ADR-0083 governed send). With no
// selected case it shows the idle "needs case" prompt and no drafting. With a
// case it offers chat + Copilot Draft Actions; a returned draft becomes an
// editable draft card. The governed "Send via SMS" affordance only appears
// for an SMS case with an active session that the operator holds, and routes
// through the confirmation modal. Network lives in injected chat/draft callbacks
// so this stays presentational and unit-testable.
import { useState } from "react";
import type { ChatResponse, DraftKind } from "@/lib/api/copilot-client";
import type { WorkbenchCase } from "@/lib/gateway/types";
import { ApiError } from "@/lib/api/http";
import { useErrorBanner } from "@/components/shell/error-banner";
import { GovernedSendModal } from "./GovernedSendModal";

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
}: {
  case: WorkbenchCase | null;
  accountId: string;
  chat: (message: string) => Promise<ChatResponse>;
  draft: (kind: DraftKind) => Promise<string>;
  onSent: () => void;
}) {
  const { showError } = useErrorBanner();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [draftBody, setDraftBody] = useState<string | null>(null);
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
      if (res.draftCard) setDraftBody(res.draftCard.body);
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
    } catch (err) {
      reportError(err, "Draft generation failed");
    } finally {
      setBusy(false);
    }
  }

  function handleSent() {
    setDraftBody(null);
    setModalOpen(false);
    onSent();
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
          <strong style={{ fontSize: "0.8rem" }}>Draft</strong>
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
