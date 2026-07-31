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
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  clearMemorySlot,
  correctMemorySlot,
  eraseCustomerMemory,
  getMemoryAudit,
} from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { MemoryAuditEntry, MemoryAuditView, MemoryPreferenceSlot } from "@/lib/gateway/types";
import { PREFERENCE_SLOTS } from "@/lib/gateway/types";
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
  // 0.0.5 S17: per-row, not a constant. It used to be the literal "copilot
  // proposal" in the JSX, which was true while an `employee_confirmed` slot row
  // could ONLY have come from accepting a copilot proposal. FR-25 gives a
  // supervisor a way to write one directly, so the constant would now label
  // their own correction as a copilot proposal they accepted. A dismissed row
  // still knows its origin — it IS a proposal_dismissed audit row.
  origin: string;
  decider: string;
  at: number;
}

const ACCEPTED_ORIGIN =
  "copilot proposal or supervisor correction — the slot row does not say which";
const DISMISSED_ORIGIN = "copilot proposal";

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
      origin: ACCEPTED_ORIGIN,
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
      origin: DISMISSED_ORIGIN,
      decider: e.actorUsername ?? e.actorAccountId ?? "—",
      at: e.at,
    }));
  return [...accepted, ...dismissed].sort((a, b) => b.at - a.at);
}

// 0.0.5 S22 (FR-34a): the per-customer memory-health strip.
//
// Four facts a supervisor cannot get from the tables below without counting rows
// by eye: how old this customer's memory is, how often it has been corrected,
// when it last reached a prompt, and what has been deleted. Composed from reads
// that ALREADY EXIST -- everything but last-injection recency is derived from
// the same payload the tables render, and that one is a scalar the audit read
// now returns.
//
// A `{label, value}` pair, not a bare number, for the same reason the Memory Hub
// uses that shape: "2" beside "Corrections" means nothing, and "2 recorded" under
// "Value corrections (S07 preference_updated rows)" means exactly one thing.
export interface MemoryHealthFact {
  key: string;
  label: string;
  value: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;

function agoDays(from: number, now: number): number {
  return Math.max(0, Math.floor((now - from) / DAY_MS));
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

export function deriveMemoryHealth(view: MemoryAuditView, now: number): MemoryHealthFact[] {
  // OLDEST, not newest: the strip exists to show when a preference has gone
  // stale, and the newest slot would report the memory as fresher than it is.
  const oldest = view.slots.reduce<number | null>(
    (acc, s) => (acc === null || s.createdAt < acc ? s.createdAt : acc),
    null,
  );
  const corrections = view.history.filter((e) => e.action === "preference_updated").length;
  const clears = view.history.filter((e) => e.action === "preference_cleared").length;
  const erasures = view.history.filter((e) => e.action === "memory_erased").length;

  return [
    {
      key: "slots",
      label: "Slots on file, and how long the oldest has been remembered",
      value:
        oldest === null
          ? "none on file"
          : `${view.slots.length} on file · oldest ${plural(agoDays(oldest, now), "day")}`,
    },
    {
      key: "corrections",
      label:
        "Value corrections — writes that replaced an existing value with a different one " +
        "(S07 preference_updated rows). A first write is not a correction.",
      value: `${corrections} recorded`,
    },
    {
      key: "lastInjection",
      label:
        "Last time this customer's memory reached a prompt (S09 injection ledger, " +
        "windowed by the ledger's own retention — 'never' also reads as 'not recorded " +
        "on this backend')",
      value:
        view.lastInjectionAt === null
          ? "never"
          : `${plural(agoDays(view.lastInjectionAt, now), "day")} ago`,
    },
    {
      key: "clears",
      // Kept apart rather than summed: one slot cleared and a whole binding
      // erased are different events, and a customer who asked to be forgotten
      // must not disappear into a "2 deletions" total.
      label: "Deletions — per-slot clears and whole-binding erasures, counted separately",
      value: `${plural(clears, "slot clear")} · ${plural(erasures, "whole-binding erasure")}`,
    },
  ];
}

// 0.0.5 S17 (FR-25/US12): what the fail-review link carries in its query string.
// `slot` and `value` are SUGGESTIONS the supervisor edits; `tag`/`from` are the
// review it came from, and they are what the correction's evidence records.
export interface CorrectionPrefill {
  caseId: string | null;
  slot: MemoryPreferenceSlot | null;
  value: string;
  tag: string | null;
  from: string | null;
}

function isPreferenceSlot(value: string | null): value is MemoryPreferenceSlot {
  return value !== null && (PREFERENCE_SLOTS as readonly string[]).includes(value);
}

// PREFERENCE_SLOTS is the closed four-slot list (ADR-0111), so index 0 always
// exists — the array's element type just does not say so.
const DEFAULT_CORRECTION_SLOT = PREFERENCE_SLOTS[0] as MemoryPreferenceSlot;

// Read from the URL rather than trusted: an unknown slot is dropped to null
// (the select falls back to its own first option) instead of being pushed at the
// governed write, which would reject it anyway.
export function readCorrectionPrefill(
  params: URLSearchParams | null,
): CorrectionPrefill | null {
  const slot = params?.get("slot") ?? null;
  const value = params?.get("value") ?? "";
  const from = params?.get("from") ?? null;
  if (!isPreferenceSlot(slot) && !value && !from) return null;
  return {
    caseId: params?.get("case") ?? null,
    slot: isPreferenceSlot(slot) ? slot : null,
    value,
    tag: params?.get("tag") ?? null,
    from,
  };
}

/**
 * The correction's own provenance line, on the `evidence` param the L4 write
 * path has always accepted.
 *
 * Same idea as the lexicon prefill's `nl_prefill` record, and for the same
 * reason: `source` is framework-derived `employee_confirmed` either way — a
 * supervisor confirmed it — so without this the row cannot say that the words
 * were suggested to them by a failed review, nor whether they changed them.
 *
 * Returns undefined for a correction the supervisor typed from scratch: no
 * prefill, no origin claim.
 *
 * Deliberately composed from the tag and the subject ref, never from the review
 * COMMENT: L4's write scan hard-rejects injection patterns in evidence (S08/D2),
 * and the comment is free text. Its content is already in the value, where the
 * supervisor has read it.
 */
export function correctionEvidence(
  prefill: CorrectionPrefill | null,
  submittedValue: string,
): string | undefined {
  if (!prefill) return undefined;
  const origin = [prefill.tag && `tagged ${prefill.tag}`, prefill.from && `on ${prefill.from}`]
    .filter(Boolean)
    .join(" ");
  const changed =
    prefill.value.trim() === submittedValue.trim()
      ? "the supervisor confirmed the suggested value unchanged"
      : "the supervisor replaced the suggested value";
  return `Prefilled from a failed review${origin ? ` ${origin}` : ""}; ${changed}.`;
}

export function MemoryAuditConsole() {
  // useSearchParams returns null outside a router context (this component's own
  // unit tests), the CopilotDashboard `?case=` deep-link precedent.
  const searchParams = useSearchParams();
  const [prefill] = useState<CorrectionPrefill | null>(() =>
    readCorrectionPrefill(searchParams),
  );
  const [caseId, setCaseId] = useState(() => prefill?.caseId ?? "");
  const [view, setView] = useState<MemoryAuditView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmClearSlot, setConfirmClearSlot] = useState<MemoryPreferenceSlot | null>(null);
  const [confirmErase, setConfirmErase] = useState(false);
  const [correctSlot, setCorrectSlot] = useState<MemoryPreferenceSlot>(
    () => prefill?.slot ?? DEFAULT_CORRECTION_SLOT,
  );
  const [correctValue, setCorrectValue] = useState(() => prefill?.value ?? "");
  const [correctBusy, setCorrectBusy] = useState(false);
  const [correctDone, setCorrectDone] = useState<string | null>(null);

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

  // FR-25: a link that arrives with a case id loads it, so "one click" really is
  // one. Without one -- an auto-handled record has no case -- the panel still
  // opens with the slot and value suggested, and the supervisor names the case.
  useEffect(() => {
    if (prefill?.caseId) void load(prefill.caseId);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount only: the
    // prefill is read once from the URL and never changes.
  }, []);

  // The correction itself: the SAME governed upsert_preference the copilot
  // panel uses, with the supervisor as actor and `employee_confirmed` derived
  // server-side. The evidence line is the only thing this slice adds to it.
  async function correct() {
    const value = correctValue.trim();
    if (!caseId.trim() || !value) return;
    setCorrectBusy(true);
    setError(null);
    setCorrectDone(null);
    try {
      await correctMemorySlot(
        caseId.trim(),
        correctSlot,
        value,
        correctionEvidence(prefill, value),
      );
      setCorrectDone(`Saved ${SLOT_LABELS[correctSlot]}.`);
      await load(caseId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save the correction");
    } finally {
      setCorrectBusy(false);
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

      {/* FR-25/US12. Rendered whether or not a review sent the supervisor here:
          the console could already clear and erase a preference but not correct
          one, so the prefill had nowhere to land. Prefilled, it is one click
          away from done; empty, it is the correction affordance that was
          missing. Either way the value is in an editable field first -- a
          suggestion the supervisor confirms, never an auto-write (NFR-3). */}
      <section
        aria-label="Correct a preference"
        style={{ border: "1px solid #e2e2e2", borderRadius: "0.5rem", padding: "0.75rem" }}
      >
        <h2 style={{ fontSize: "1.125rem", margin: "0 0 0.35rem" }}>
          Correct a preference
        </h2>
        {prefill ? (
          <p style={{ fontSize: "0.8rem", color: "#555", margin: "0 0 0.5rem" }}>
            Prefilled from a failed review
            {prefill.tag ? ` tagged ${prefill.tag}` : ""}
            {prefill.from ? ` on ${prefill.from}` : ""}. Read it, change anything
            that is wrong, then save — the entry records that it started as a
            suggestion and whether you changed it.
            {prefill.caseId ? null : " Enter the case id for this customer first."}
          </p>
        ) : null}
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
          <label htmlFor="memory-correct-slot">Slot</label>
          <select
            id="memory-correct-slot"
            value={correctSlot}
            onChange={(e) => setCorrectSlot(e.target.value as MemoryPreferenceSlot)}
          >
            {PREFERENCE_SLOTS.map((slot) => (
              <option key={slot} value={slot}>
                {SLOT_LABELS[slot]}
              </option>
            ))}
          </select>
          <label htmlFor="memory-correct-value">Value</label>
          <input
            id="memory-correct-value"
            value={correctValue}
            onChange={(e) => setCorrectValue(e.target.value)}
            style={{ minWidth: "18rem" }}
          />
          <button
            type="button"
            disabled={correctBusy || !caseId.trim() || !correctValue.trim()}
            onClick={() => void correct()}
          >
            Save correction
          </button>
        </div>
        {correctDone ? (
          <p style={{ fontSize: "0.8rem", color: "#555", margin: "0.35rem 0 0" }}>
            {correctDone}
          </p>
        ) : null}
      </section>

      {view ? (
        <>
          <section aria-label="Memory health" style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
            {deriveMemoryHealth(view, Date.now()).map((fact) => (
              <div
                key={fact.key}
                data-fact={fact.key}
                style={{
                  border: "1px solid #e2e2e2",
                  borderRadius: "0.5rem",
                  padding: "0.5rem 0.75rem",
                  maxWidth: "18rem",
                }}
              >
                <p style={{ fontSize: "1.05rem", fontWeight: 600, margin: "0 0 0.15rem" }}>
                  {fact.value}
                </p>
                <p style={{ fontSize: "0.75rem", opacity: 0.7, margin: 0 }}>{fact.label}</p>
              </div>
            ))}
          </section>

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
                    {/* 0.0.5 S17: the write's own note on where the value came
                        from. `source` says a human confirmed it; only this says
                        whether the words were suggested to them. Stored since
                        0.0.3 and never rendered until now. */}
                    <th style={th}>Evidence</th>
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
                      <td style={td}>{s.evidence ?? "—"}</td>
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
                        <td style={td}>{row.origin}</td>
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
