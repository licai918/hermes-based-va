"use client";

// Read-only Auto-Handled Audit detail (ADR-0086): summary header, full
// conversation timeline (prior auto-handled turns de-emphasized), and a
// tool-call evidence panel surfacing input/output summaries plus any
// unavailable-system error class. No claim/assign/draft/send controls. Fetching
// the record server-side records a Workbench Audit Log audit_view entry.
import { getAutoHandled } from "@/lib/api/audit-client";
import type { ThreadAuthor } from "@/lib/gateway/types";
import { formatChannel, formatRelativeTime } from "@/lib/format";
import {
  Notice,
  cardStyle,
  ddStyle,
  dlStyle,
  dtStyle,
  failureStyle,
  isNotFound,
  mutedStyle,
  pageStyle,
  useAsync,
} from "./shared";

const AUTHOR_LABELS: Record<ThreadAuthor, string> = {
  customer: "Customer",
  hermes: "Hermes",
  workbench: "Workbench",
};

export function AutoHandledDetail({ recordId }: { recordId: string }) {
  const state = useAsync(() => getAutoHandled(recordId), [recordId]);
  const now = Date.now();

  return (
    <section style={pageStyle}>
      <h1>Auto-handled record</h1>

      {state.status === "loading" && (
        <Notice role="status">Loading record…</Notice>
      )}

      {state.status === "error" && isNotFound(state.error) && (
        <Notice>
          Record not found.{" "}
          <a href="/copilot/audit/auto-handled">Back to audit list</a>
        </Notice>
      )}

      {state.status === "error" && !isNotFound(state.error) && (
        <Notice role="alert" style={failureStyle}>
          Could not load this record.
        </Notice>
      )}

      {state.status === "ready" && (
        <>
          <header style={cardStyle}>
            <h2 style={{ margin: "0 0 0.5rem" }}>
              {state.data.record.identitySummary}
            </h2>
            <dl style={dlStyle}>
              <dt style={dtStyle}>Channel</dt>
              <dd style={ddStyle}>{formatChannel(state.data.record.channel)}</dd>
              <dt style={dtStyle}>Outcome</dt>
              <dd style={ddStyle}>{state.data.record.outcome}</dd>
              <dt style={dtStyle}>Last activity</dt>
              <dd style={ddStyle}>
                {formatRelativeTime(state.data.record.lastActivityAt, now)}
              </dd>
            </dl>
            {state.data.record.toolFailure && (
              <p style={failureStyle}>
                Tool failure occurred during this interaction.
              </p>
            )}
          </header>

          <section style={cardStyle}>
            <h2 style={{ marginTop: 0 }}>Conversation</h2>
            <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {state.data.record.timeline.map((m) => (
                <li
                  key={m.messageId}
                  style={{
                    padding: "0.5rem 0",
                    borderBottom: "1px solid #f0f0f0",
                    opacity: m.autoHandled ? 0.6 : 1,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      gap: "0.5rem",
                      alignItems: "baseline",
                    }}
                  >
                    <strong>{AUTHOR_LABELS[m.author]}</strong>
                    <span style={mutedStyle}>
                      {formatRelativeTime(m.at, now)}
                    </span>
                    {m.autoHandled && (
                      <span style={mutedStyle}>· auto-handled</span>
                    )}
                  </div>
                  <p style={{ margin: "0.25rem 0 0" }}>{m.body}</p>
                </li>
              ))}
            </ol>
          </section>

          <section style={cardStyle}>
            <h2 style={{ marginTop: 0 }}>Tool-call evidence</h2>
            {state.data.record.toolCalls.length === 0 ? (
              <Notice>No tool calls were recorded.</Notice>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {state.data.record.toolCalls.map((tc, i) => (
                  <li
                    key={`${tc.tool}.${tc.action}.${i}`}
                    style={{
                      padding: "0.5rem 0",
                      borderBottom: "1px solid #f0f0f0",
                    }}
                  >
                    <div>
                      <strong>
                        {tc.tool}.{tc.action}
                      </strong>
                    </div>
                    <div style={mutedStyle}>Input: {tc.inputSummary}</div>
                    <div style={mutedStyle}>Output: {tc.outputSummary}</div>
                    {tc.errorClass && (
                      <div style={failureStyle}>
                        Error class: {tc.errorClass}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </section>
  );
}
