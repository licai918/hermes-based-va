"use client";

// Read-only Auto-Handled Audit list (ADR-0037/0085). Full-width table with no
// Copilot Gateway; rows link to the per-record detail. Sorted most-recent-first
// is the BFF's responsibility; this view renders records as delivered.
import { listAutoHandled } from "@/lib/api/audit-client";
import { formatChannel, formatRelativeTime } from "@/lib/format";
import {
  Notice,
  failureStyle,
  tableStyle,
  tdStyle,
  thStyle,
  useAsync,
} from "./shared";

export function AutoHandledList() {
  const state = useAsync(() => listAutoHandled(), []);
  const now = Date.now();

  if (state.status === "loading") {
    return <Notice role="status">Loading auto-handled records…</Notice>;
  }
  if (state.status === "error") {
    return (
      <Notice role="alert" style={failureStyle}>
        Could not load auto-handled records.
      </Notice>
    );
  }

  const { records } = state.data;
  if (records.length === 0) {
    return <Notice>No auto-handled records to review.</Notice>;
  }

  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <th style={thStyle}>Channel</th>
          <th style={thStyle}>Identity</th>
          <th style={thStyle}>Last message</th>
          <th style={thStyle}>Outcome</th>
          <th style={thStyle}>Tool summary</th>
          <th style={thStyle}>Tool failure</th>
          <th style={thStyle}>Last activity</th>
        </tr>
      </thead>
      <tbody>
        {records.map((r) => (
          <tr key={r.recordId}>
            <td style={tdStyle}>{formatChannel(r.channel)}</td>
            <td style={tdStyle}>
              <a href={`/copilot/audit/auto-handled/${r.recordId}`}>
                {r.identitySummary}
              </a>
            </td>
            <td style={tdStyle}>{r.lastMessagePreview}</td>
            <td style={tdStyle}>{r.outcome}</td>
            <td style={tdStyle}>{r.toolSummary}</td>
            <td style={tdStyle}>
              {r.toolFailure ? (
                <span style={failureStyle}>Tool failure</span>
              ) : (
                <span aria-hidden="true" style={{ color: "#bbb" }}>
                  —
                </span>
              )}
            </td>
            <td style={tdStyle}>{formatRelativeTime(r.lastActivityAt, now)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
