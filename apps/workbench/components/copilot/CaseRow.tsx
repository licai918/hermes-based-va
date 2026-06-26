"use client";

// One Case Queue row (ADR-0079 columns). Presentational: it renders a single
// Human Intervention Case and reports selection upward. The identity cell holds
// the selection control as a real button so the row is keyboard accessible and
// unit-testable without a clickable-<tr> hack.
import type { WorkbenchCase } from "@/lib/gateway/types";
import { formatChannel, formatRelativeTime, formatStatus } from "@/lib/format";

// "Mine" for the signed-in account, "Unassigned" for an empty assignee, else the
// owning account id verbatim (ADR-0079 Case Assignee column).
export function formatAssignee(
  assigneeAccountId: string | null,
  accountId: string,
): string {
  if (assigneeAccountId === null) return "Unassigned";
  if (assigneeAccountId === accountId) return "Mine";
  return assigneeAccountId;
}

const cell: React.CSSProperties = {
  padding: "0.4rem 0.6rem",
  borderBottom: "1px solid #eee",
  verticalAlign: "top",
  fontSize: "0.8125rem",
};

export function CaseRow({
  case: workbenchCase,
  accountId,
  selected,
  onSelect,
  now = Date.now(),
}: {
  case: WorkbenchCase;
  accountId: string;
  selected: boolean;
  onSelect: (caseId: string) => void;
  now?: number;
}) {
  const c = workbenchCase;
  return (
    <tr style={{ background: selected ? "#eef4ff" : "transparent" }}>
      <td style={cell}>
        {c.urgent ? (
          <span aria-label="Urgent" style={{ color: "#b00020", fontWeight: 700 }}>
            ⚑ Urgent
          </span>
        ) : null}
      </td>
      <td style={cell}>{formatChannel(c.channel)}</td>
      <td style={cell}>
        <button
          type="button"
          onClick={() => onSelect(c.caseId)}
          aria-pressed={selected}
          style={{
            background: "none",
            border: "none",
            padding: 0,
            font: "inherit",
            color: "#1a4fd6",
            textAlign: "left",
            cursor: "pointer",
            fontWeight: selected ? 700 : 500,
          }}
        >
          {c.identitySummary}
        </button>
      </td>
      <td style={cell}>{c.contactReason}</td>
      <td style={cell}>{formatStatus(c.status)}</td>
      <td style={cell}>{formatAssignee(c.assigneeAccountId, accountId)}</td>
      <td style={cell}>{formatRelativeTime(c.lastActivityAt, now)}</td>
      <td style={{ ...cell, color: "#555" }}>{c.lastMessagePreview}</td>
      <td style={cell}>
        {c.toolFailure ? (
          <span aria-label="Tool failure" style={{ color: "#b00020" }}>
            ⚠ Tool failure
          </span>
        ) : null}
      </td>
    </tr>
  );
}
