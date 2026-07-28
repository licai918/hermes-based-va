"use client";

// L7 Semantic Lexicon console (0.0.5 S02, FR-3/FR-8, ADR-0093 admin route
// group): the human gate over the domain language the business speaks. Sibling
// of AgentExperienceConsole -- same container/view split, same "a decided entry
// stays in the list showing its new status, never removed", same per-row error
// so one failed action does not blank the console.
//
// What it adds over the L6 console, and why:
//   * a manual-add form (US1: an admin adds "TOEE = TOEE TIRE" and it is LIVE,
//     no deploy -- the row lands confirmed because the admin IS the gate);
//   * inline edit of the MAPPING, which is an in-place UPDATE (D7): the entry
//     keeps its id and its hit_count, so this is a Save, never a delete+create;
//   * Retire on a confirmed entry, which is a different act from Reject;
//   * a status filter over the same one governed read (S01's list action,
//     extended -- there is no second read);
//   * an UNATTRIBUTED badge on an `admin_manual` row with no decider (D20).
import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  type AddLexiconEntryInput,
  addLexiconEntry,
  decideLexiconEntry,
  editLexiconEntry,
  listLexiconEntries,
} from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { LexiconEntry, LexiconEntryKind, LexiconStatus } from "@/lib/gateway/types";

const KINDS: LexiconEntryKind[] = ["alias", "normalizer", "default_rule"];
const STATUS_FILTERS: (LexiconStatus | "all")[] = [
  "all",
  "proposed",
  "confirmed",
  "rejected",
  "retired",
];

// Sentinel so the add form shares the one `busyId` the row actions use.
const ADD_BUSY_ID = "__add__";

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "0.25rem 1rem 0.25rem 0",
  borderBottom: "1px solid #ccc",
};
const td: React.CSSProperties = {
  padding: "0.35rem 1rem 0.35rem 0",
  verticalAlign: "top",
};
const alert: React.CSSProperties = { color: "#8a1c1c" };

function formatTime(ms: number | null): string {
  return ms === null ? "—" : new Date(ms).toLocaleString();
}

function message(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

// D2's keep exemption means `false` is NOT "no PII on this row": a span that
// exactly equals the entry's own surface/canonical form is waived (it must be --
// the seeded "205 55 16" matches the phone pattern, and redacting it would
// destroy the evidence an admin needs), and the waiver is recorded only in the
// audit row's `pii_keep_exempt`, which no UI reads. So the false case says what
// actually happened -- no span was removed -- and never claims the row is clean.
const PII_FOOTNOTE =
  "“Scrubbed” means the write scan removed a PII span from the evidence. " +
  "“None removed” means no span was removed — it is not a statement that the " +
  "row is free of PII: a span identical to the entry’s own surface or canonical " +
  "form is deliberately kept, and that waiver is recorded only in the audit log.";

export type LexiconConsoleViewProps = {
  entries: LexiconEntry[];
  loading: boolean;
  error: string | null;
  busyId: string | null;
  rowErrors: Record<string, string>;
  addError: string | null;
  statusFilter: LexiconStatus | "all";
  onStatusFilter: (status: LexiconStatus | "all") => void;
  onDecide: (entry: LexiconEntry, decision: "confirm" | "reject" | "retire") => void;
  onEdit: (entry: LexiconEntry, canonicalForm: string) => void;
  onAdd: (input: AddLexiconEntryInput) => Promise<boolean> | void;
};

function EntryRow({
  entry,
  busyId,
  rowErrors,
  onDecide,
  onEdit,
}: Pick<LexiconConsoleViewProps, "busyId" | "rowErrors" | "onDecide" | "onEdit"> & {
  entry: LexiconEntry;
}) {
  const [editing, setEditing] = useState(false);
  const [canonical, setCanonical] = useState(entry.canonicalForm);
  const busy = busyId === entry.id;
  const editable = entry.status === "proposed" || entry.status === "confirmed";

  return (
    <tr>
      <td style={td}>{entry.domain}</td>
      <td style={td}>{entry.entryKind}</td>
      <td style={td}>{entry.surfaceForm}</td>
      <td style={td}>
        {editing ? (
          <span style={{ display: "inline-flex", gap: "0.4rem" }}>
            <input
              aria-label={`Canonical form for ${entry.surfaceForm}`}
              value={canonical}
              onChange={(e) => setCanonical(e.target.value)}
            />
            <button
              type="button"
              aria-label={`Save ${entry.surfaceForm}`}
              disabled={busy}
              onClick={() => {
                setEditing(false);
                onEdit(entry, canonical);
              }}
            >
              Save
            </button>
          </span>
        ) : (
          entry.canonicalForm
        )}
      </td>
      <td style={td}>{entry.status}</td>
      <td style={td}>
        {entry.provenance}
        {entry.provenanceUnattributed ? (
          <>
            {" "}
            <strong
              style={alert}
              title={
                "This row claims a human administrator authored it but names " +
                "nobody. Written before the provenance path became fail-closed; " +
                "treat it as unverified and re-decide it."
              }
            >
              UNATTRIBUTED
            </strong>
          </>
        ) : null}
      </td>
      <td style={td}>{entry.deciderAccountId ?? "—"}</td>
      <td style={td}>{entry.hitCount}</td>
      <td style={td}>{entry.piiRedacted ? "Scrubbed" : "None removed"}</td>
      <td style={td}>{formatTime(entry.createdAt)}</td>
      <td style={td}>
        <span style={{ display: "inline-flex", flexDirection: "column", gap: "0.25rem" }}>
          <span style={{ display: "inline-flex", gap: "0.4rem" }}>
            {entry.status === "proposed" ? (
              <>
                <button
                  type="button"
                  aria-label={`Approve ${entry.surfaceForm}`}
                  disabled={busy}
                  onClick={() => onDecide(entry, "confirm")}
                >
                  Approve
                </button>
                <button
                  type="button"
                  aria-label={`Reject ${entry.surfaceForm}`}
                  disabled={busy}
                  onClick={() => onDecide(entry, "reject")}
                >
                  Reject
                </button>
              </>
            ) : null}
            {entry.status === "confirmed" ? (
              <button
                type="button"
                aria-label={`Retire ${entry.surfaceForm}`}
                disabled={busy}
                onClick={() => onDecide(entry, "retire")}
              >
                Retire
              </button>
            ) : null}
            {editable && !editing ? (
              <button
                type="button"
                aria-label={`Edit ${entry.surfaceForm}`}
                disabled={busy}
                onClick={() => {
                  setCanonical(entry.canonicalForm);
                  setEditing(true);
                }}
              >
                Edit
              </button>
            ) : null}
            {!editable && !editing ? "—" : null}
          </span>
          {rowErrors[entry.id] ? (
            <span role="alert" style={{ ...alert, fontSize: "0.8rem" }}>
              {rowErrors[entry.id]}
            </span>
          ) : null}
        </span>
      </td>
    </tr>
  );
}

export function LexiconConsoleView({
  entries,
  loading,
  error,
  busyId,
  rowErrors,
  addError,
  statusFilter,
  onStatusFilter,
  onDecide,
  onEdit,
  onAdd,
}: LexiconConsoleViewProps) {
  const [domain, setDomain] = useState("");
  const [entryKind, setEntryKind] = useState<LexiconEntryKind>("alias");
  const [surfaceForm, setSurfaceForm] = useState("");
  const [canonicalForm, setCanonicalForm] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const ok = await onAdd({ domain, entryKind, surfaceForm, canonicalForm });
    if (ok) {
      setSurfaceForm("");
      setCanonicalForm("");
    }
  }

  return (
    <section
      aria-label="Semantic lexicon"
      style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
    >
      <div>
        <label htmlFor="lexicon-status-filter" style={{ marginRight: "0.5rem" }}>
          Status
        </label>
        <select
          id="lexicon-status-filter"
          value={statusFilter}
          onChange={(e) => onStatusFilter(e.target.value as LexiconStatus | "all")}
        >
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {loading ? <p>Loading…</p> : null}
      {error ? (
        <p role="alert" style={alert}>
          {error}
        </p>
      ) : null}

      {!loading && !error ? (
        entries.length > 0 ? (
          <>
            <table style={{ borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={th}>Domain</th>
                  <th style={th}>Kind</th>
                  <th style={th}>Surface form</th>
                  <th style={th}>Canonical form</th>
                  <th style={th}>Status</th>
                  <th style={th}>Provenance</th>
                  <th style={th}>Decider</th>
                  <th style={th}>Hits</th>
                  <th style={th}>PII scan</th>
                  <th style={th}>Proposed</th>
                  <th style={th}></th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <EntryRow
                    key={e.id}
                    entry={e}
                    busyId={busyId}
                    rowErrors={rowErrors}
                    onDecide={onDecide}
                    onEdit={onEdit}
                  />
                ))}
              </tbody>
            </table>
            <p style={{ fontSize: "0.8rem", color: "#555", margin: 0 }}>
              {PII_FOOTNOTE}
            </p>
          </>
        ) : (
          <p>No lexicon entries yet.</p>
        )
      ) : null}

      <form onSubmit={handleSubmit} style={{ maxWidth: "24rem" }}>
        <h2 style={{ fontSize: "1.0625rem", marginTop: 0 }}>Add entry</h2>
        <p style={{ fontSize: "0.8rem", color: "#555", marginTop: 0 }}>
          An entry you add here is confirmed immediately and attributed to you —
          you are the gate, so there is nothing further to approve.
        </p>

        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="lexicon-domain" style={{ display: "block", fontWeight: 600 }}>
            Domain
          </label>
          <input
            id="lexicon-domain"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
        </div>

        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="lexicon-kind" style={{ display: "block", fontWeight: 600 }}>
            Kind
          </label>
          <select
            id="lexicon-kind"
            value={entryKind}
            onChange={(e) => setEntryKind(e.target.value as LexiconEntryKind)}
            style={{ width: "100%", boxSizing: "border-box" }}
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="lexicon-surface" style={{ display: "block", fontWeight: 600 }}>
            Surface form
          </label>
          <input
            id="lexicon-surface"
            value={surfaceForm}
            onChange={(e) => setSurfaceForm(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
        </div>

        <div style={{ marginBottom: "0.75rem" }}>
          <label
            htmlFor="lexicon-canonical"
            style={{ display: "block", fontWeight: 600 }}
          >
            Canonical form
          </label>
          <input
            id="lexicon-canonical"
            value={canonicalForm}
            onChange={(e) => setCanonicalForm(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
        </div>

        <button type="submit" disabled={busyId === ADD_BUSY_ID}>
          Add entry
        </button>

        {addError ? (
          <p role="alert" style={{ ...alert, marginBottom: 0 }}>
            {addError}
          </p>
        ) : null}
      </form>
    </section>
  );
}

export function LexiconConsole() {
  const [entries, setEntries] = useState<LexiconEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [addError, setAddError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<LexiconStatus | "all">("all");

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setEntries(
        await listLexiconEntries(
          statusFilter === "all" ? {} : { status: statusFilter },
        ),
      );
    } catch (e) {
      setEntries([]);
      setError(message(e, "Failed to load lexicon entries"));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function clearRowError(id: string) {
    setRowErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  // A decided/edited entry is REPLACED in place, never removed: the governed
  // response is the row's new state, so the console shows the outcome instead of
  // making the admin guess. A failure leaves the row exactly as it was and
  // actionable to retry.
  async function mutate(entry: LexiconEntry, run: () => Promise<LexiconEntry>, fail: string) {
    setBusyId(entry.id);
    clearRowError(entry.id);
    try {
      const updated = await run();
      setEntries((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
    } catch (e) {
      setRowErrors((prev) => ({ ...prev, [entry.id]: message(e, fail) }));
    } finally {
      setBusyId(null);
    }
  }

  async function handleAdd(input: AddLexiconEntryInput): Promise<boolean> {
    setBusyId(ADD_BUSY_ID);
    setAddError(null);
    try {
      await addLexiconEntry(input);
      await reload();
      return true;
    } catch (e) {
      setAddError(message(e, "Failed to add the entry"));
      return false;
    } finally {
      setBusyId(null);
    }
  }

  return (
    <LexiconConsoleView
      entries={entries}
      loading={loading}
      error={error}
      busyId={busyId}
      rowErrors={rowErrors}
      addError={addError}
      statusFilter={statusFilter}
      onStatusFilter={setStatusFilter}
      onDecide={(entry, decision) =>
        void mutate(
          entry,
          () => decideLexiconEntry(entry.id, decision),
          `Failed to ${decision} this entry`,
        )
      }
      onEdit={(entry, canonicalForm) =>
        void mutate(
          entry,
          () => editLexiconEntry(entry.id, { canonicalForm }),
          "Failed to save this edit",
        )
      }
      onAdd={handleAdd}
    />
  );
}
