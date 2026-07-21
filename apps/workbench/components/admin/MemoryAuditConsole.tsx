"use client";

// Supervisor Memory Audit View (0.0.3 S20, FR-20, ADR-0093 admin route group):
// per-customer Customer Memory slots with full write attribution
// (source/actor/timestamps) plus the append-only write-history trail
// (dismissed proposals, attributed clears), with a governed Clear action.
// Closes the 0.0.2 PAC-1 caveat -- "who changed this" is answerable here, not
// SQL. There is no existing supervisor-facing customer picker to reuse (the
// copilot preferences panel lives inside an open case), so the input is the
// case_id backing that case -- the same identity-binding key every other
// Customer Memory read/write in this codebase resolves through.
import { useState } from "react";
import { clearMemorySlot, getMemoryAudit } from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { MemoryAuditView, MemoryPreferenceSlot } from "@/lib/gateway/types";
import { SLOT_LABELS } from "@/components/copilot/CustomerPreferences";

const th: React.CSSProperties = { textAlign: "left", padding: "0.25rem 1rem 0.25rem 0", borderBottom: "1px solid #ccc" };
const td: React.CSSProperties = { padding: "0.35rem 1rem 0.35rem 0", verticalAlign: "top" };

function formatTime(ms: number): string {
  return new Date(ms).toLocaleString();
}

export function MemoryAuditConsole() {
  const [caseId, setCaseId] = useState("");
  const [view, setView] = useState<MemoryAuditView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmClearSlot, setConfirmClearSlot] = useState<MemoryPreferenceSlot | null>(null);

  async function load(id: string) {
    if (!id.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setView(await getMemoryAudit(id.trim()));
    } catch (e) {
      setView(null);
      setError(e instanceof ApiError ? e.message : "Failed to load memory audit view");
    } finally {
      setLoading(false);
    }
  }

  async function clear(slot: MemoryPreferenceSlot) {
    setError(null);
    try {
      await clearMemorySlot(caseId.trim(), slot);
      setConfirmClearSlot(null);
      await load(caseId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to clear the slot");
    }
  }

  return (
    <section aria-label="Memory audit" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void load(caseId);
        }}
        style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}
      >
        <label htmlFor="memory-audit-case-id" style={{ fontWeight: 600 }}>
          Case ID
        </label>
        <input
          id="memory-audit-case-id"
          value={caseId}
          onChange={(e) => setCaseId(e.target.value)}
          placeholder="case_ar_urgent"
        />
        <button type="submit" disabled={loading || !caseId.trim()}>
          Load
        </button>
      </form>

      {error ? (
        <p role="alert" style={{ color: "#8a1c1c" }}>
          {error}
        </p>
      ) : null}

      {view ? (
        <>
          <div>
            <h2 style={{ fontSize: "1.125rem", margin: "0 0 0.5rem" }}>Current slots</h2>
            {view.slots.length === 0 ? (
              <p>No preference slots are set for this customer.</p>
            ) : (
              <table style={{ borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={th}>Slot</th>
                    <th style={th}>Value</th>
                    <th style={th}>Source</th>
                    <th style={th}>Actor</th>
                    <th style={th}>Updated</th>
                    <th style={th}></th>
                  </tr>
                </thead>
                <tbody>
                  {view.slots.map((s) => (
                    <tr key={s.slot}>
                      <td style={td}>{SLOT_LABELS[s.slot]}</td>
                      <td style={td}>{s.value}</td>
                      <td style={td}>{s.source ?? "—"}</td>
                      <td style={td}>{s.actorAccountId ?? "AI (unattributed)"}</td>
                      <td style={td}>{formatTime(s.updatedAt)}</td>
                      <td style={td}>
                        {confirmClearSlot === s.slot ? (
                          <span style={{ display: "inline-flex", gap: "0.35rem" }}>
                            Clear this preference?
                            <button type="button" onClick={() => clear(s.slot)}>
                              Confirm clear
                            </button>
                            <button type="button" onClick={() => setConfirmClearSlot(null)}>
                              Cancel
                            </button>
                          </span>
                        ) : (
                          <button
                            type="button"
                            aria-label={`Clear ${SLOT_LABELS[s.slot]}`}
                            onClick={() => setConfirmClearSlot(s.slot)}
                          >
                            Clear
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div>
            <h2 style={{ fontSize: "1.125rem", margin: "0 0 0.5rem" }}>Write history</h2>
            {view.history.length === 0 ? (
              <p>No audit history for this customer yet.</p>
            ) : (
              <table style={{ borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={th}>When</th>
                    <th style={th}>Action</th>
                    <th style={th}>Slot</th>
                    <th style={th}>Actor</th>
                    <th style={th}>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {view.history.map((entry) => (
                    <tr key={entry.entryId}>
                      <td style={td}>{formatTime(entry.at)}</td>
                      <td style={td}>{entry.action}</td>
                      <td style={td}>{entry.slot ?? "—"}</td>
                      <td style={td}>{entry.actorUsername ?? entry.actorAccountId ?? "—"}</td>
                      <td style={td}>{entry.detail ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}
