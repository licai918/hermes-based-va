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
import { clearMemorySlot, eraseCustomerMemory, getMemoryAudit } from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { MemoryAuditEntry, MemoryAuditView, MemoryPreferenceSlot } from "@/lib/gateway/types";
import { SLOT_LABELS } from "@/components/copilot/CustomerPreferences";

const th: React.CSSProperties = { textAlign: "left", padding: "0.25rem 1rem 0.25rem 0", borderBottom: "1px solid #ccc" };
const td: React.CSSProperties = { padding: "0.35rem 1rem 0.35rem 0", verticalAlign: "top" };

function formatTime(ms: number): string {
  return new Date(ms).toLocaleString();
}

function slotLabel(slot: string | null): string {
  if (!slot) return "—";
  return (SLOT_LABELS as Record<string, string>)[slot] ?? slot;
}

// 0.0.5 S07 (FR-9): the write-history Detail column shows a readable old->new
// pair for a preference_updated row instead of the raw JSON details blob
// entry.detail otherwise falls back to; every other action keeps entry.detail
// unchanged. A preference_updated row that somehow carries no pair (a partial
// write, or a row written before this slice) falls back the same way rather
// than rendering "undefined". A pure function, same as deriveProposalHistory
// below, so it's unit-testable without going through rendering.
//
// Both sides are QUOTED (review finding 5). An empty string is a legal slot
// value -- _require_value only rejects non-strings and >200 chars -- so an
// unquoted pair rendered a dangling " → email" with nothing on the left, and a
// value that itself contains the arrow ran the two sides together. JSON.stringify
// is the one-call fix: it delimits both sides and escapes embedded quotes.
export function historyDetail(entry: MemoryAuditEntry): string {
  if (entry.action === "preference_updated" && entry.oldValue !== undefined && entry.newValue !== undefined) {
    return `${JSON.stringify(entry.oldValue)} → ${JSON.stringify(entry.newValue)}`;
  }
  return entry.detail ?? "";
}

export interface ProposalHistoryRow {
  key: string;
  slot: string;
  value: string;
  outcome: "accepted" | "dismissed";
  decider: string;
  at: number;
}

// S16 (FR-17, audit finding 14): a dismissed proposal writes no preference
// slot (S15's dismiss_proposal is audit-only), so the slot list alone can
// never show it. Both outcomes are already in the S20 payload -- accepted =
// the employee_confirmed slot rows (S15's model: that slot row IS the
// acceptance record; there is deliberately no separate proposal_accepted
// audit action, out of scope here), dismissed = proposal_dismissed history
// rows. Every proposal originates from the copilot draft turn, so origin is
// a constant, not a per-row field. Decider is actorUsername ?? actorAccountId
// for a dismissed row; MemorySlotAttribution carries no actorUsername (the
// slots query never joins workbench_account, unlike the audit query), so an
// accepted row's decider is its actorAccountId.
export function deriveProposalHistory(view: MemoryAuditView): ProposalHistoryRow[] {
  const accepted: ProposalHistoryRow[] = view.slots
    .filter((s) => s.source === "employee_confirmed")
    .map((s) => ({
      key: `accepted-${s.slot}`,
      slot: s.slot,
      value: s.value,
      outcome: "accepted",
      decider: s.actorAccountId ?? "—",
      at: s.updatedAt,
    }));
  const dismissed: ProposalHistoryRow[] = view.history
    .filter((e) => e.action === "proposal_dismissed")
    .map((e) => ({
      key: `dismissed-${e.entryId}`,
      slot: e.slot ?? "—",
      value: e.value ?? "—",
      outcome: "dismissed",
      decider: e.actorUsername ?? e.actorAccountId ?? "—",
      at: e.at,
    }));
  return [...accepted, ...dismissed].sort((a, b) => b.at - a.at);
}

export function MemoryAuditConsole() {
  const [caseId, setCaseId] = useState("");
  const [view, setView] = useState<MemoryAuditView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmClearSlot, setConfirmClearSlot] = useState<MemoryPreferenceSlot | null>(null);
  const [confirmErase, setConfirmErase] = useState(false);

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
      await load(caseId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to clear the slot");
    } finally {
      // Close the inline confirm/cancel UI on BOTH success and failure -- a
      // failed clear used to leave it hanging open under the error banner
      // (final-review Minor). The error banner still shows the failure; the
      // supervisor re-opens the confirm to retry.
      setConfirmClearSlot(null);
    }
  }

  // FR-13 (US7): the whole-binding erase. Same confirm-then-act shape as the
  // per-slot clear above, and the same reload afterwards -- the point of the
  // reload here is that the write history it re-fetches now CONTAINS the erase's
  // own 4+1 audit rows, which is what PAC-3 asks a supervisor to be able to see.
  async function erase() {
    setError(null);
    try {
      await eraseCustomerMemory(caseId.trim());
      await load(caseId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to erase this customer's memory");
    } finally {
      setConfirmErase(false);
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
            {/* The erase sits beside the heading, not in the table, and stays
                available when the table is EMPTY on purpose: this view shows the
                verified binding's slots, while the erase also clears every
                linked channel's provisional binding (D10) -- which can hold
                slots this table never renders. Gating the button on
                view.slots.length would hide the erase in exactly the case the
                supervisor most needs it. */}
            <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem", margin: "0 0 0.5rem" }}>
              <h2 style={{ fontSize: "1.125rem", margin: 0 }}>Current slots</h2>
              {confirmErase ? (
                <span style={{ display: "inline-flex", gap: "0.35rem", alignItems: "baseline" }}>
                  Erase every remembered preference for this customer, including
                  linked channels? This cannot be undone.
                  <button type="button" onClick={() => void erase()}>
                    Confirm erase
                  </button>
                  <button type="button" onClick={() => setConfirmErase(false)}>
                    Cancel
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  aria-label="Erase all memory for this customer"
                  onClick={() => setConfirmErase(true)}
                >
                  Erase all memory
                </button>
              )}
            </div>
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
                      <td style={td}>{historyDetail(entry)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div>
            <h2 style={{ fontSize: "1.125rem", margin: "0 0 0.5rem" }}>Proposal history</h2>
            {(() => {
              const rows = deriveProposalHistory(view);
              return rows.length === 0 ? (
                <p>No proposal outcomes for this customer yet.</p>
              ) : (
                <table style={{ borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={th}>Proposal</th>
                      <th style={th}>Origin</th>
                      <th style={th}>Outcome</th>
                      <th style={th}>Decider</th>
                      <th style={th}>When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.key}>
                        <td style={td}>
                          {slotLabel(row.slot)}: {row.value}
                        </td>
                        <td style={td}>copilot proposal</td>
                        <td style={td}>{row.outcome === "accepted" ? "Accepted" : "Dismissed"}</td>
                        <td style={td}>{row.decider}</td>
                        <td style={td}>{formatTime(row.at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              );
            })()}
          </div>
        </>
      ) : null}
    </section>
  );
}
