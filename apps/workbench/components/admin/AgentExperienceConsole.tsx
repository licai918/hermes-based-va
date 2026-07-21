"use client";

// L6 Agent-experience review queue (0.0.3 S22/S24, FR-23/FR-24, ADR-0093 admin
// route group): every proposed/confirmed/rejected entry the store holds, with
// kind, content, status, proposer context, and timestamp. Every "proposed" row
// gets Accept/Reject (S24's human confirm gate, US23: the agent only "learns"
// what a human approved), reusing the S15 PendingProposals interaction shape
// -- the container (this component) owns the BFF calls; a decided entry stays
// in the list showing its new status + decider, never removed; a failed
// decision leaves the row actionable to retry (its error shows inline, the row
// itself is untouched). Loads on mount: unlike the per-customer Memory Audit
// console, there is no case_id to key off (the L6 store is global, not
// customer-bound).
import { useEffect, useState } from "react";
import { confirmExperience, listAgentExperience, rejectExperience } from "@/lib/api/admin-client";
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
  // Per-row decision error, keyed by entry id, so one failed Accept/Reject
  // doesn't blank out the whole console -- the row stays actionable to retry.
  const [decisionErrors, setDecisionErrors] = useState<Record<string, string>>({});
  const [decidingId, setDecidingId] = useState<string | null>(null);

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

  async function decide(entry: AgentExperienceEntry, action: "accept" | "reject") {
    setDecidingId(entry.id);
    setDecisionErrors((prev) => {
      const next = { ...prev };
      delete next[entry.id];
      return next;
    });
    try {
      const decided = action === "accept" ? await confirmExperience(entry.id) : await rejectExperience(entry.id);
      setEntries((prev) => prev && prev.map((e) => (e.id === decided.id ? decided : e)));
    } catch (e) {
      setDecisionErrors((prev) => ({
        ...prev,
        [entry.id]: e instanceof ApiError ? e.message : `Failed to ${action} this proposal`,
      }));
    } finally {
      setDecidingId(null);
    }
  }

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
                <th style={th}>Decider</th>
                <th style={th}>Proposer context</th>
                <th style={th}>Proposed</th>
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td style={td}>{e.kind}</td>
                  <td style={td}>{e.content}</td>
                  <td style={td}>{e.status}</td>
                  <td style={td}>{e.deciderAccountId ?? "—"}</td>
                  <td style={td}>
                    {e.proposerContext ? JSON.stringify(e.proposerContext) : "—"}
                  </td>
                  <td style={td}>{formatTime(e.createdAt)}</td>
                  <td style={td}>
                    {e.status === "proposed" ? (
                      <span style={{ display: "inline-flex", flexDirection: "column", gap: "0.25rem" }}>
                        <span style={{ display: "inline-flex", gap: "0.4rem" }}>
                          <button
                            type="button"
                            aria-label={`Accept agent-experience entry ${e.id}`}
                            disabled={decidingId === e.id}
                            onClick={() => void decide(e, "accept")}
                          >
                            Accept
                          </button>
                          <button
                            type="button"
                            aria-label={`Reject agent-experience entry ${e.id}`}
                            disabled={decidingId === e.id}
                            onClick={() => void decide(e, "reject")}
                          >
                            Reject
                          </button>
                        </span>
                        {decisionErrors[e.id] ? (
                          <span role="alert" style={{ color: "#8a1c1c", fontSize: "0.8rem" }}>
                            {decisionErrors[e.id]}
                          </span>
                        ) : null}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
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
