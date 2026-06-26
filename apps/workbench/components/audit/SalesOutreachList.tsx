"use client";

// Read-only Sales-Outreach Audit list (ADR-0050/0085). Low-priority
// `sales_outreach` follow-up cases are audit-sampled only (never in the rep
// queue); rows link to the per-case detail.
import { listSalesOutreach } from "@/lib/api/audit-client";
import { formatChannel, formatRelativeTime, formatStatus } from "@/lib/format";
import {
  Notice,
  failureStyle,
  tableStyle,
  tdStyle,
  thStyle,
  useAsync,
} from "./shared";

export function SalesOutreachList() {
  const state = useAsync(() => listSalesOutreach(), []);
  const now = Date.now();

  if (state.status === "loading") {
    return <Notice role="status">Loading sales-outreach cases…</Notice>;
  }
  if (state.status === "error") {
    return (
      <Notice role="alert" style={failureStyle}>
        Could not load sales-outreach cases.
      </Notice>
    );
  }

  const { cases } = state.data;
  if (cases.length === 0) {
    return <Notice>No sales outreach cases to review.</Notice>;
  }

  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <th style={thStyle}>Case ID</th>
          <th style={thStyle}>Identity</th>
          <th style={thStyle}>Channel</th>
          <th style={thStyle}>Contact reason</th>
          <th style={thStyle}>Last message</th>
          <th style={thStyle}>Status</th>
          <th style={thStyle}>Created</th>
          <th style={thStyle}>Last activity</th>
        </tr>
      </thead>
      <tbody>
        {cases.map((c) => (
          <tr key={c.caseId}>
            <td style={tdStyle}>{c.caseId}</td>
            <td style={tdStyle}>
              <a href={`/copilot/audit/sales-outreach/${c.caseId}`}>
                {c.identitySummary}
              </a>
            </td>
            <td style={tdStyle}>{formatChannel(c.channel)}</td>
            <td style={tdStyle}>{c.contactReason}</td>
            <td style={tdStyle}>{c.lastMessagePreview}</td>
            <td style={tdStyle}>{formatStatus(c.status)}</td>
            <td style={tdStyle}>{formatRelativeTime(c.openedAt, now)}</td>
            <td style={tdStyle}>{formatRelativeTime(c.lastActivityAt, now)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
