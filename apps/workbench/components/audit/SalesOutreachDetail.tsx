"use client";

// Read-only Sales-Outreach Audit detail (ADR-0050/0086). Case metadata only:
// no operational Case Thread Context action header, since these records are
// audit-sampled and not employee drafting queue items.
import { getSalesOutreach } from "@/lib/api/audit-client";
import { formatChannel, formatRelativeTime, formatStatus } from "@/lib/format";
import {
  Notice,
  cardStyle,
  ddStyle,
  dlStyle,
  dtStyle,
  failureStyle,
  isNotFound,
  pageStyle,
  useAsync,
} from "./shared";

export function SalesOutreachDetail({ caseId }: { caseId: string }) {
  const state = useAsync(() => getSalesOutreach(caseId), [caseId]);
  const now = Date.now();

  return (
    <section style={pageStyle}>
      <h1>Sales outreach case</h1>

      {state.status === "loading" && (
        <Notice role="status">Loading case…</Notice>
      )}

      {state.status === "error" && isNotFound(state.error) && (
        <Notice>
          Case not found.{" "}
          <a href="/copilot/audit/sales-outreach">Back to audit list</a>
        </Notice>
      )}

      {state.status === "error" && !isNotFound(state.error) && (
        <Notice role="alert" style={failureStyle}>
          Could not load this case.
        </Notice>
      )}

      {state.status === "ready" && (
        <>
          <header style={cardStyle}>
            <h2 style={{ margin: "0 0 0.5rem" }}>
              {state.data.case.identitySummary}
            </h2>
            {state.data.case.urgent && <p style={failureStyle}>Urgent</p>}
            <dl style={dlStyle}>
              <dt style={dtStyle}>Channel</dt>
              <dd style={ddStyle}>{formatChannel(state.data.case.channel)}</dd>
              <dt style={dtStyle}>Contact reason</dt>
              <dd style={ddStyle}>{state.data.case.contactReason}</dd>
              <dt style={dtStyle}>Status</dt>
              <dd style={ddStyle}>{formatStatus(state.data.case.status)}</dd>
              <dt style={dtStyle}>Opened</dt>
              <dd style={ddStyle}>
                {formatRelativeTime(state.data.case.openedAt, now)}
              </dd>
              <dt style={dtStyle}>Last activity</dt>
              <dd style={ddStyle}>
                {formatRelativeTime(state.data.case.lastActivityAt, now)}
              </dd>
            </dl>
          </header>

          <section style={cardStyle}>
            <h2 style={{ marginTop: 0 }}>Latest message</h2>
            <p style={{ margin: 0 }}>{state.data.case.lastMessagePreview}</p>
          </section>
        </>
      )}
    </section>
  );
}
