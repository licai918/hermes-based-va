"use client";

// Case Thread Context (ADR-0082): a sticky case-metadata header with workbench
// actions over a read-only, chronological timeline. Presentational — every
// mutation is reported through a callback so the container owns the BFF calls and
// refetches. Prior Auto-Handled turns stay visible but de-emphasized; the active
// Human Intervention segment is highlighted.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import type { ThreadAuthor, ThreadMessage, WorkbenchCase } from "@/lib/gateway/types";
import { formatChannel, formatRelativeTime, formatStatus } from "@/lib/format";
import { formatAssignee } from "./CaseRow";

const AUTHOR_LABELS: Record<ThreadAuthor, string> = {
  customer: "Customer",
  hermes: "Hermes",
  workbench: "Workbench",
};

function isSupervisorOrAdmin(role: WorkbenchRoleId): boolean {
  return role === WORKBENCH_ROLES.supervisor || role === WORKBENCH_ROLES.admin;
}

const META_ITEM: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "0.1rem" };
const META_LABEL: React.CSSProperties = { fontSize: "0.7rem", textTransform: "uppercase", color: "#777" };
const NEAR_BOTTOM_PX = 80;

function isNearBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
}

export function ThreadContext({
  case: workbenchCase,
  messages,
  accountId,
  role,
  onClaim,
  onResolve,
  onSetPriority,
  onSetContactReason,
  onAssign,
  now = Date.now(),
}: {
  case: WorkbenchCase;
  messages: ThreadMessage[];
  accountId: string;
  role: WorkbenchRoleId;
  onClaim: () => void;
  onResolve: () => void;
  onSetPriority: (urgent: boolean) => void;
  onSetContactReason: (contactReason: string) => void;
  onAssign: (assigneeAccountId: string) => void;
  now?: number;
}) {
  const c = workbenchCase;
  const elevated = isSupervisorOrAdmin(role);
  const [editingReason, setEditingReason] = useState(false);
  const [reasonDraft, setReasonDraft] = useState(c.contactReason);
  const [assignDraft, setAssignDraft] = useState("");
  const timelineRef = useRef<HTMLOListElement>(null);
  const stickToBottomRef = useRef(true);
  const firstLoadRef = useRef(true);

  useEffect(() => {
    stickToBottomRef.current = true;
    firstLoadRef.current = true;
  }, [c.caseId]);

  useLayoutEffect(() => {
    const el = timelineRef.current;
    if (el === null) return;
    if (firstLoadRef.current || stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
      stickToBottomRef.current = true;
    }
    firstLoadRef.current = false;
  }, [messages]);

  function saveReason() {
    const next = reasonDraft.trim();
    if (next.length > 0) onSetContactReason(next);
    setEditingReason(false);
  }

  return (
    <section
      aria-label="Case thread context"
      style={{ display: "flex", flexDirection: "column", minHeight: 0, height: "100%" }}
    >
      <header
        style={{
          position: "sticky",
          top: 0,
          background: "#fafafa",
          borderBottom: "1px solid #e2e2e2",
          padding: "0.6rem 0.75rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.6rem",
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: "1.25rem", alignItems: "flex-start" }}>
          <div style={META_ITEM}>
            <span style={META_LABEL}>Channel</span>
            <span>{formatChannel(c.channel)}</span>
          </div>
          <div style={META_ITEM}>
            <span style={META_LABEL}>Identity</span>
            <span style={{ fontWeight: 600 }}>{c.identitySummary}</span>
          </div>
          <div style={META_ITEM}>
            <span style={META_LABEL}>Contact reason</span>
            {editingReason ? (
              <span style={{ display: "inline-flex", gap: "0.3rem" }}>
                <input
                  aria-label="Contact reason"
                  value={reasonDraft}
                  onChange={(e) => setReasonDraft(e.target.value)}
                />
                <button type="button" onClick={saveReason}>
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setReasonDraft(c.contactReason);
                    setEditingReason(false);
                  }}
                >
                  Cancel
                </button>
              </span>
            ) : (
              <span style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
                {c.contactReason}
                <button type="button" onClick={() => setEditingReason(true)}>
                  Edit reason
                </button>
              </span>
            )}
          </div>
          <div style={META_ITEM}>
            <span style={META_LABEL}>Priority</span>
            <span style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
              {c.urgent ? (
                <span aria-label="Urgent" style={{ color: "#b00020", fontWeight: 700 }}>
                  ⚑ Urgent
                </span>
              ) : (
                <span style={{ color: "#777" }}>Normal</span>
              )}
              {elevated ? (
                <button type="button" onClick={() => onSetPriority(!c.urgent)}>
                  {c.urgent ? "Clear urgent" : "Mark urgent"}
                </button>
              ) : null}
            </span>
          </div>
          <div style={META_ITEM}>
            <span style={META_LABEL}>Status</span>
            <span>{formatStatus(c.status)}</span>
          </div>
          <div style={META_ITEM}>
            <span style={META_LABEL}>Assignee</span>
            <span>{formatAssignee(c.assigneeAccountId, accountId)}</span>
          </div>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
          {c.assigneeAccountId === null ? (
            <button type="button" onClick={onClaim}>
              Claim case
            </button>
          ) : null}
          {c.status !== "resolved" ? (
            <button type="button" onClick={onResolve}>
              Resolve case
            </button>
          ) : null}
          {elevated ? (
            <span style={{ display: "inline-flex", gap: "0.3rem", alignItems: "center" }}>
              <input
                aria-label="Assign to account"
                placeholder="account id"
                value={assignDraft}
                onChange={(e) => setAssignDraft(e.target.value)}
              />
              <button
                type="button"
                onClick={() => {
                  const next = assignDraft.trim();
                  if (next.length > 0) onAssign(next);
                }}
              >
                Assign
              </button>
            </span>
          ) : null}
        </div>
      </header>

      <ol
        ref={timelineRef}
        aria-label="Thread timeline"
        onScroll={(e) => {
          stickToBottomRef.current = isNearBottom(e.currentTarget);
        }}
        style={{
          listStyle: "none",
          margin: 0,
          padding: "0.5rem 0.75rem",
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: "0.4rem",
        }}
      >
        {messages.map((m) => (
          <li
            key={m.messageId}
            data-auto-handled={m.autoHandled ? "true" : undefined}
            data-active-segment={m.activeCaseSegment ? "true" : undefined}
            style={{
              padding: "0.4rem 0.5rem",
              borderRadius: 6,
              opacity: m.autoHandled ? 0.55 : 1,
              background: m.activeCaseSegment ? "#eef4ff" : "transparent",
              borderLeft: m.activeCaseSegment ? "3px solid #1a4fd6" : "3px solid transparent",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.72rem", color: "#666" }}>
              <span style={{ fontWeight: 600 }}>{AUTHOR_LABELS[m.author]}</span>
              <span>{formatRelativeTime(m.at, now)}</span>
            </div>
            <div style={{ fontSize: "0.85rem" }}>{m.body}</div>
          </li>
        ))}
      </ol>
    </section>
  );
}
