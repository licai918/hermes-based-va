"use client";

// Conversation Simulator (FR-8/FR-9, 0.0.3 S02/S03): phone + composer over the
// real gateway webhook ingress, thread view read back through the same Case
// Thread Context read the copilot case view uses. The reply is asynchronous
// (webhook ack -> background turn -> mirrored to message_turn), so an accepted
// send starts polling the thread until a new Hermes turn shows up or the
// window (~60s) elapses. FR-12: once the gateway's webhook creates a case for
// this phone, a link out to that case's real Case Thread Context appears.
//
// SMS/email channel switcher (0.0.3 S18, FR-11): `channel` picks which
// identity (phone vs simulated address) and which BFF route pair
// (messages/thread vs email/thread) the composer + read-back use. SMS keeps
// its exact prior behavior -- the sms branch of every function below is
// unchanged logic, just reached through the same `channel === "sms"` guard
// the email branch is written against. The "link identity" control (S05) is
// SMS-only here: extending it to email is S05's own territory, not this
// slice's, and cross-channel merge is explicitly S19 -- out of scope.
import { useCallback, useEffect, useRef, useState } from "react";
import { ROUTES } from "@toee/shared";
import { useErrorBanner } from "@/components/shell/error-banner";
import * as simulator from "@/lib/api/simulator-client";
import { ApiError } from "@/lib/api/http";
import { formatRelativeTime } from "@/lib/format";
import type { ThreadMessage } from "@/lib/gateway/types";
import { hasNewOutboundReply } from "@/lib/simulator-polling";
import {
  EMAIL_PRESETS,
  IDENTITY_PRESETS,
  LINK_IDENTITY_TARGET,
  resolvePresetEmail,
  resolvePresetPhone,
  type IdentityPresetId,
} from "@/lib/simulator-identity";

const DEFAULT_PHONE = "+15550001001";
const DEFAULT_EMAIL = "unmatched@sim.example";
const POLL_INTERVAL_MS = 2_000;
const POLL_MAX_ATTEMPTS = 30; // ~60s at POLL_INTERVAL_MS

type Channel = "sms" | "email";
type SendState = "idle" | "pending" | "accepted" | "rejected" | "gateway-down";

const AUTHOR_LABEL: Record<ThreadMessage["author"], string> = {
  customer: "Customer",
  hermes: "Hermes",
  workbench: "Workbench",
};

export function Simulator({ now = Date.now() }: { now?: number } = {}) {
  const { showError } = useErrorBanner();
  const [channel, setChannel] = useState<Channel>("sms");
  const [phone, setPhone] = useState(DEFAULT_PHONE);
  const [email, setEmail] = useState(DEFAULT_EMAIL);
  const [subject, setSubject] = useState("");
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [sendState, setSendState] = useState<SendState>("idle");
  const [sendMessage, setSendMessage] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [linkState, setLinkState] = useState<"idle" | "pending" | "linked" | "error">(
    "idle",
  );
  const [linkMessage, setLinkMessage] = useState<string | null>(null);
  const pollRef = useRef<{ timer: ReturnType<typeof setInterval> | null; attempts: number }>({
    timer: null,
    attempts: 0,
  });
  // Tracks the (channel, identity) pair the user is actually looking at right
  // now, kept in sync with every place channel/phone/email state changes
  // (switchIdentity, the identity inputs' onChange). loadThread and
  // handleSend's continuation check against this ref -- not the `channel`/
  // `phone`/`email` state or a closed-over variable -- so a slow in-flight
  // fetch for an identity the user has since switched away from (preset pick
  // / reset / channel toggle) can't repaint stale messages/caseId or restart
  // polling for the old identity (FR-13, extended to the channel dimension by
  // S18/FR-11).
  const activeIdentityRef = useRef<{ channel: Channel; identity: string }>({
    channel: "sms",
    identity: DEFAULT_PHONE,
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
    async (forChannel: Channel, forIdentity: string): Promise<ThreadMessage[]> => {
      try {
        const res =
          forChannel === "sms"
            ? await simulator.getSimulatorThread(forIdentity)
            : await simulator.getSimulatorEmailThread(forIdentity);
        // Stale-response guard: if the user switched identity or channel
        // (preset/reset/toggle) while this fetch was in flight, this no
        // longer matches what's on screen -- drop the response instead of
        // repainting the old thread over the new one.
        const active = activeIdentityRef.current;
        if (forChannel === active.channel && forIdentity === active.identity) {
          setMessages(res.messages);
          setCaseId(res.caseId);
        }
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
    void loadThread("sms", DEFAULT_PHONE);
    // Initial load only -- re-fetching on every keystroke of the identity
    // field would flood the BFF; the field's onBlur below re-triggers a load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startPolling(before: ThreadMessage[], forChannel: Channel, forIdentity: string) {
    stopPolling();
    pollRef.current.attempts = 0;
    setPolling(true);
    pollRef.current.timer = setInterval(() => {
      pollRef.current.attempts += 1;
      void loadThread(forChannel, forIdentity).then((after) => {
        if (hasNewOutboundReply(before, after) || pollRef.current.attempts >= POLL_MAX_ATTEMPTS) {
          stopPolling();
        }
      });
    }, POLL_INTERVAL_MS);
  }

  // Fresh identity (any channel) -- shared by the preset pickers, reset, and
  // the channel toggle (FR-9/FR-13, S18/FR-11). Stops any in-flight poll for
  // the old identity, drops the conversationId so the next send opens a new
  // server-side conversation, and reloads the thread for the new identity
  // (empty for a never-seen identity, existing history for a fixed preset
  // reused across runs).
  function switchIdentity(nextChannel: Channel, nextIdentity: string) {
    stopPolling();
    activeIdentityRef.current = { channel: nextChannel, identity: nextIdentity };
    setChannel(nextChannel);
    if (nextChannel === "sms") setPhone(nextIdentity);
    else setEmail(nextIdentity);
    setConversationId(undefined);
    setSendState("idle");
    setSendMessage(null);
    setLinkState("idle");
    setLinkMessage(null);
    void loadThread(nextChannel, nextIdentity);
  }

  function handlePresetSelect(id: IdentityPresetId) {
    switchIdentity("sms", resolvePresetPhone(id));
  }

  function handleEmailPresetSelect(id: IdentityPresetId) {
    switchIdentity("email", resolvePresetEmail(id));
  }

  // Channel toggle (S18/FR-11): switching SMS <-> email resets the thread
  // view exactly like switchIdentity does for a preset pick -- a stale SMS
  // thread must never keep showing under the email tab (or vice versa) --
  // but keeps each channel's own current identity value rather than
  // generating a fresh one.
  function handleChannelChange(next: Channel) {
    if (next === channel) return;
    switchIdentity(next, next === "sms" ? phone : email);
  }

  // "Link identity" control (S05, FR-13): simulates the ingress event that
  // links the CURRENT simulated channel identity to a verified customer,
  // through the production Identity Graph linking path (no direct DB writes --
  // see lib/bff/copilot/simulator.ts's handleSimulatorLinkIdentity). Once
  // linked, the customer's NEXT inbound message resolves verified_customer and
  // the ADR-0112 provisional-merge trigger fires, making FR-19's cross-channel
  // continuity observable (S19 wires the merge itself). SMS-only: extending
  // this control to email identities is S05's own territory, not S18's.
  async function handleLinkIdentity() {
    const forPhone = phone;
    setLinkState("pending");
    setLinkMessage(null);
    try {
      await simulator.linkSimulatorIdentity({
        channelIdentity: forPhone,
        shopifyCustomerId: LINK_IDENTITY_TARGET.shopifyCustomerId,
        companyName: LINK_IDENTITY_TARGET.companyName,
      });
      // Stale-response guard, same as loadThread/handleSend: don't paint a
      // "Linked" status for a phone the user has since switched away from.
      if (forPhone === activeIdentityRef.current.identity) setLinkState("linked");
    } catch (err) {
      if (forPhone === activeIdentityRef.current.identity) {
        setLinkState("error");
        setLinkMessage(
          err instanceof ApiError ? err.message : "Failed to link identity",
        );
      }
    }
  }

  // Reset / new-conversation (FR-13): clears the local thread view and picks
  // a fresh unknown-caller identity for the CURRENT channel, so PAC runs are
  // repeatable without cross-contamination. Server-side data for the old
  // identity/case is left alone (NFR-4 territory is simulated identities
  // only, never a real customer or inbox).
  function handleReset() {
    setMessages([]);
    setCaseId(null);
    setDraft("");
    if (channel === "email") {
      setSubject("");
      switchIdentity("email", resolvePresetEmail("unknown"));
    } else {
      switchIdentity("sms", resolvePresetPhone("unknown"));
    }
  }

  async function handleSend() {
    const body = draft.trim();
    if (body.length === 0 || sendState === "pending") return;
    const before = messages;
    setSendState("pending");
    setSendMessage(null);
    const forChannel = channel;
    const forIdentity = forChannel === "sms" ? phone : email;
    try {
      const res =
        forChannel === "sms"
          ? await simulator.sendSimulatorMessage({ fromPhone: forIdentity, body, conversationId })
          : await simulator.sendSimulatorEmail({ from: forIdentity, subject, body, conversationId });
      setDraft("");
      // Same stale-response guard as loadThread: a Reset/preset/channel
      // switch during this send must not repopulate conversationId or
      // restart polling for the identity the user has since left (FR-13).
      const active = activeIdentityRef.current;
      const stillActive = forChannel === active.channel && forIdentity === active.identity;
      if (stillActive) setConversationId(res.conversationId);
      if (res.accepted) {
        setSendState("accepted");
        if (stillActive) startPolling(before, forChannel, forIdentity);
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
        {channel === "sms"
          ? "Sends a simulated customer SMS through the real gateway webhook (no bypass chat) and reads the agent's reply back once it lands."
          : "Sends a simulated customer email through the real runtime webhook (no bypass chat) and reads the agent's reply back once it lands. Addresses are simulated only, never a real inbox (NFR-4)."}
      </p>

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <label htmlFor="sim-channel" style={{ fontSize: "0.8rem", color: "#666" }}>
          Channel
        </label>
        <select
          id="sim-channel"
          value={channel}
          onChange={(e) => handleChannelChange(e.target.value as Channel)}
        >
          <option value="sms">SMS</option>
          <option value="email">Email</option>
        </select>
      </div>

      {channel === "sms" ? (
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
          <label htmlFor="sim-phone" style={{ fontSize: "0.8rem", color: "#666" }}>
            From phone
          </label>
          <input
            id="sim-phone"
            value={phone}
            onChange={(e) => {
              activeIdentityRef.current = { channel: "sms", identity: e.target.value };
              setPhone(e.target.value);
            }}
            onBlur={() => void loadThread("sms", phone)}
          />

          <label htmlFor="sim-identity-preset" style={{ fontSize: "0.8rem", color: "#666" }}>
            Identity preset
          </label>
          {/* value="" is intentional: a one-shot select, not a controlled
              "current preset" -- picking a preset fires switchIdentity and
              the control resets to the placeholder rather than tracking
              phone. */}
          <select
            id="sim-identity-preset"
            value=""
            onChange={(e) => {
              const id = e.target.value as IdentityPresetId;
              if (id) handlePresetSelect(id);
            }}
          >
            <option value="" disabled>
              Choose a preset…
            </option>
            {IDENTITY_PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>

          <button type="button" onClick={handleReset}>
            Reset / new conversation
          </button>

          <button
            type="button"
            onClick={() => void handleLinkIdentity()}
            disabled={linkState === "pending"}
          >
            Link identity to {LINK_IDENTITY_TARGET.companyName} (verified)
          </button>

          {caseId ? (
            <a href={`${ROUTES.copilot}?case=${encodeURIComponent(caseId)}`}>
              Open case in copilot
            </a>
          ) : null}
        </div>
      ) : (
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
          <label htmlFor="sim-email" style={{ fontSize: "0.8rem", color: "#666" }}>
            From address
          </label>
          <input
            id="sim-email"
            value={email}
            onChange={(e) => {
              activeIdentityRef.current = { channel: "email", identity: e.target.value };
              setEmail(e.target.value);
            }}
            onBlur={() => void loadThread("email", email)}
          />

          <label htmlFor="sim-subject" style={{ fontSize: "0.8rem", color: "#666" }}>
            Subject
          </label>
          <input
            id="sim-subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          />

          <label htmlFor="sim-email-identity-preset" style={{ fontSize: "0.8rem", color: "#666" }}>
            Identity preset
          </label>
          {/* Same one-shot-select shape as the SMS preset picker above. */}
          <select
            id="sim-email-identity-preset"
            value=""
            onChange={(e) => {
              const id = e.target.value as IdentityPresetId;
              if (id) handleEmailPresetSelect(id);
            }}
          >
            <option value="" disabled>
              Choose a preset…
            </option>
            {EMAIL_PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>

          <button type="button" onClick={handleReset}>
            Reset / new conversation
          </button>

          {caseId ? (
            <a href={`${ROUTES.copilot}?case=${encodeURIComponent(caseId)}`}>
              Open case in copilot
            </a>
          ) : null}
        </div>
      )}

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

      <div
        role="status"
        aria-live="polite"
        style={{ fontSize: "0.8rem", color: linkState === "error" ? "#b00020" : "#666" }}
      >
        {linkState === "pending" ? "Linking…" : null}
        {linkState === "linked"
          ? `Linked to ${LINK_IDENTITY_TARGET.companyName} (${LINK_IDENTITY_TARGET.shopifyCustomerId}). The next message from this number resolves verified.`
          : null}
        {linkState === "error" ? linkMessage ?? "Failed to link identity." : null}
      </div>
    </section>
  );
}
