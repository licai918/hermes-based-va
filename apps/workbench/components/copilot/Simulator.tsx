"use client";

// Conversation Simulator (FR-8/FR-9, 0.0.3 S02/S03): phone + composer over the
// real gateway webhook ingress, thread view read back through the same Case
// Thread Context read the copilot case view uses. The reply is asynchronous
// (webhook ack -> background turn -> mirrored to message_turn), so an accepted
// send starts polling the thread until a new Hermes turn shows up or the
// window (~60s) elapses. FR-12: once the gateway's webhook creates a case for
// this phone, a link out to that case's real Case Thread Context appears.
//
// Channel switcher + identity presets + reset are S18/S04 -- `phone` is plain
// component state (not lifted) so those slices can wire in without reshaping
// this component.
import { useCallback, useEffect, useRef, useState } from "react";
import { ROUTES } from "@toee/shared";
import { useErrorBanner } from "@/components/shell/error-banner";
import * as simulator from "@/lib/api/simulator-client";
import { ApiError } from "@/lib/api/http";
import { formatRelativeTime } from "@/lib/format";
import type { ThreadMessage } from "@/lib/gateway/types";
import { hasNewOutboundReply } from "@/lib/simulator-polling";

const DEFAULT_PHONE = "+15550001001";
const POLL_INTERVAL_MS = 2_000;
const POLL_MAX_ATTEMPTS = 30; // ~60s at POLL_INTERVAL_MS

type SendState = "idle" | "pending" | "accepted" | "rejected" | "gateway-down";

const AUTHOR_LABEL: Record<ThreadMessage["author"], string> = {
  customer: "Customer",
  hermes: "Hermes",
  workbench: "Workbench",
};

export function Simulator({ now = Date.now() }: { now?: number } = {}) {
  const { showError } = useErrorBanner();
  const [phone, setPhone] = useState(DEFAULT_PHONE);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [sendState, setSendState] = useState<SendState>("idle");
  const [sendMessage, setSendMessage] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const pollRef = useRef<{ timer: ReturnType<typeof setInterval> | null; attempts: number }>({
    timer: null,
    attempts: 0,
  });

  const stopPolling = useCallback(() => {
    if (pollRef.current.timer !== null) {
      clearInterval(pollRef.current.timer);
      pollRef.current.timer = null;
    }
    setPolling(false);
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const loadThread = useCallback(
    async (forPhone: string): Promise<ThreadMessage[]> => {
      try {
        const res = await simulator.getSimulatorThread(forPhone);
        setMessages(res.messages);
        setCaseId(res.caseId);
        return res.messages;
      } catch (err) {
        const message =
          err instanceof ApiError ? err.message : "Failed to load the simulated thread";
        showError(message, err instanceof ApiError ? `HTTP ${err.status}` : undefined);
        return [];
      }
    },
    [showError],
  );

  useEffect(() => {
    void loadThread(DEFAULT_PHONE);
    // Initial load only -- re-fetching on every keystroke of the phone field
    // would flood the BFF; the field's onBlur below re-triggers a load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startPolling(before: ThreadMessage[], forPhone: string) {
    stopPolling();
    pollRef.current.attempts = 0;
    setPolling(true);
    pollRef.current.timer = setInterval(() => {
      pollRef.current.attempts += 1;
      void loadThread(forPhone).then((after) => {
        if (hasNewOutboundReply(before, after) || pollRef.current.attempts >= POLL_MAX_ATTEMPTS) {
          stopPolling();
        }
      });
    }, POLL_INTERVAL_MS);
  }

  async function handleSend() {
    const body = draft.trim();
    if (body.length === 0 || sendState === "pending") return;
    const before = messages;
    setSendState("pending");
    setSendMessage(null);
    try {
      const res = await simulator.sendSimulatorMessage({ fromPhone: phone, body, conversationId });
      setConversationId(res.conversationId);
      setDraft("");
      if (res.accepted) {
        setSendState("accepted");
        startPolling(before, phone);
      } else {
        setSendState("rejected");
        setSendMessage("The gateway rejected the simulated message.");
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 502) {
        setSendState("gateway-down");
        setSendMessage(err.message);
      } else {
        setSendState("rejected");
        setSendMessage(
          err instanceof ApiError ? err.message : "Failed to send the simulated message",
        );
      }
    }
  }

  return (
    <section
      aria-label="Conversation Simulator"
      style={{ display: "flex", flexDirection: "column", gap: "0.75rem", maxWidth: 640 }}
    >
      <h1 style={{ margin: 0 }}>Conversation Simulator</h1>
      <p style={{ color: "#666", margin: 0, fontSize: "0.85rem" }}>
        Sends a simulated customer SMS through the real gateway webhook (no bypass
        chat) and reads the agent's reply back once it lands.
      </p>

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <label htmlFor="sim-phone" style={{ fontSize: "0.8rem", color: "#666" }}>
          From phone
        </label>
        <input
          id="sim-phone"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          onBlur={() => void loadThread(phone)}
        />
        {caseId ? (
          <a href={`${ROUTES.copilot}?case=${encodeURIComponent(caseId)}`}>
            Open case in copilot
          </a>
        ) : null}
      </div>

      <ol
        aria-label="Simulated thread"
        style={{
          listStyle: "none",
          margin: 0,
          padding: "0.5rem",
          border: "1px solid #e2e2e2",
          borderRadius: 8,
          minHeight: 200,
          maxHeight: 360,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: "0.4rem",
        }}
      >
        {messages.map((m) => (
          <li
            key={m.messageId}
            style={{
              alignSelf: m.author === "customer" ? "flex-end" : "flex-start",
              maxWidth: "85%",
            }}
          >
            <div style={{ fontSize: "0.7rem", color: "#888" }}>
              {AUTHOR_LABEL[m.author]} · {formatRelativeTime(m.at, now)}
            </div>
            <div
              style={{
                padding: "0.4rem 0.6rem",
                borderRadius: 8,
                background: m.author === "customer" ? "#1a4fd6" : "#f0f0f0",
                color: m.author === "customer" ? "#fff" : "#222",
                whiteSpace: "pre-wrap",
              }}
            >
              {m.body}
            </div>
          </li>
        ))}
      </ol>

      <div style={{ display: "flex", gap: "0.4rem" }}>
        <input
          aria-label="Simulated customer message"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleSend();
          }}
          placeholder="Type as the simulated customer…"
          style={{ flex: 1 }}
        />
        <button type="button" onClick={() => void handleSend()} disabled={sendState === "pending"}>
          Send
        </button>
      </div>

      <div
        role="status"
        aria-live="polite"
        style={{ fontSize: "0.8rem", color: sendState === "gateway-down" ? "#b00020" : "#666" }}
      >
        {sendState === "pending" ? "Sending…" : null}
        {sendState === "accepted"
          ? polling
            ? "Accepted — waiting for the agent's reply…"
            : "Accepted."
          : null}
        {sendState === "rejected" ? sendMessage ?? "The simulated message was rejected." : null}
        {sendState === "gateway-down"
          ? sendMessage ?? "Simulator gateway is unreachable."
          : null}
      </div>
    </section>
  );
}
