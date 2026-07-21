"use client";

// L6 Agent-experience minimal admin list (0.0.3 S22, FR-23, ADR-0093 admin
// route group): every proposed/confirmed/rejected entry the store holds, with
// kind, content, status, proposer context, and timestamp. Read-only by design
// -- S24 extends this same list into the Accept/Reject review queue; there are
// deliberately no decision buttons here yet. Loads on mount: unlike the
// per-customer Memory Audit console, there is no case_id to key off (the L6
// store is global, not customer-bound).
import { useEffect, useState } from "react";
import { listAgentExperience } from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { AgentExperienceEntry } from "@/lib/gateway/types";

const th: React.CSSProperties = { textAlign: "left", padding: "0.25rem 1rem 0.25rem 0", borderBottom: "1px solid #ccc" };
const td: React.CSSProperties = { padding: "0.35rem 1rem 0.35rem 0", verticalAlign: "top" };

function formatTime(ms: number | null): string {
  return ms === null ? "—" : new Date(ms).toLocaleString();
}

export function AgentExperienceConsole() {
  const [entries, setEntries] = useState<AgentExperienceEntry[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listAgentExperience()
      .then((result) => {
        if (!cancelled) setEntries(result);
      })
      .catch((e) => {
        if (cancelled) return;
        setEntries(null);
        setError(e instanceof ApiError ? e.message : "Failed to load agent-experience entries");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section aria-label="Agent experience" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {loading ? <p>Loading…</p> : null}
      {error ? (
        <p role="alert" style={{ color: "#8a1c1c" }}>
          {error}
        </p>
      ) : null}
      {!loading && !error ? (
        entries && entries.length > 0 ? (
          <table style={{ borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={th}>Kind</th>
                <th style={th}>Content</th>
                <th style={th}>Status</th>
                <th style={th}>Proposer context</th>
                <th style={th}>Proposed</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td style={td}>{e.kind}</td>
                  <td style={td}>{e.content}</td>
                  <td style={td}>{e.status}</td>
                  <td style={td}>
                    {e.proposerContext ? JSON.stringify(e.proposerContext) : "—"}
                  </td>
                  <td style={td}>{formatTime(e.createdAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p>No agent-experience entries yet.</p>
        )
      ) : null}
    </section>
  );
}
