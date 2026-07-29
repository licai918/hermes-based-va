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
//   * a plain-language draft box (0.0.5 S17, FR-24/US11): the admin types
//     "TOEE 也叫拓意", the copilot fills the four fields in, the admin reads them
//     and presses Add. The Add is the SAME governed action as always -- the
//     draft writes nothing -- and what the confirmed row carries is a record of
//     which of its words started as a machine's suggestion.
import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  type AddLexiconEntryInput,
  addLexiconEntry,
  decideLexiconEntry,
  draftLexiconEntry,
  editLexiconEntry,
  listLexiconEntries,
} from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { LexiconDraft } from "@/lib/gateway/hermes-agent-client";
import type {
  LexiconEntry,
  LexiconEntryHealth,
  LexiconEntryKind,
  LexiconHealthLeg,
  LexiconStatus,
} from "@/lib/gateway/types";

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
const DRAFT_BUSY_ID = "__draft__";

// 0.0.5 S17 (FR-24). What the console remembers about a draft while the admin
// looks at it: the sentence they typed, what the copilot suggested, and which
// model said so. Held in component state and never sent anywhere until the
// admin presses Add.
export type NlPrefill = {
  text: string;
  fields: NonNullable<LexiconDraft["fields"]>;
  model?: string;
};

// The four form fields, browser name -> the column name a later reader will see
// on the row. The provenance record is written in the row's own vocabulary, not
// the browser's, because the person reading it is looking at the row.
const PREFILL_FIELD_COLUMNS = {
  domain: "domain",
  entryKind: "entry_kind",
  surfaceForm: "surface_form",
  canonicalForm: "canonical_form",
} as const;

/**
 * The record that tells a prefilled-and-accepted value apart from a hand-typed
 * one (D20's other half).
 *
 * D20 made `admin_manual` fail closed without an actor, because provenance that
 * names nobody is unfalsifiable. A prefill raises the mirror-image question: the
 * admin IS attached and the row IS their assertion — a field they read and did
 * not change is still something they asserted — but "an administrator typed
 * this" would no longer be the whole truth if nothing said a model went first.
 *
 * So the write keeps `provenance = admin_manual` and its decider, and carries
 * this beside it on `proposer_context`, the param the shared write path already
 * reads and D2's scan already covers. `suggested` is the copilot's own words
 * VERBATIM, because for a field the admin rewrote that is the only place they
 * survive; the two lists are the fast answer to "did a human choose this word".
 *
 * Returns `undefined` when there was no draft — a hand-typed entry carries no
 * key at all, which is what makes the distinction readable rather than inferred.
 */
export function nlPrefillProvenance(
  prefill: NlPrefill | null,
  submitted: AddLexiconEntryInput,
): Record<string, unknown> | undefined {
  if (!prefill) return undefined;
  const acceptedUnchanged: string[] = [];
  const changedByAdmin: string[] = [];
  const suggested: Record<string, string> = {};
  for (const [formName, column] of Object.entries(PREFILL_FIELD_COLUMNS)) {
    const drafted = prefill.fields[formName as keyof typeof PREFILL_FIELD_COLUMNS];
    // A field the copilot did not suggest is in neither list: the admin typed it
    // with nothing in front of them, which is the plain hand-typed case.
    if (typeof drafted !== "string" || drafted.length === 0) continue;
    suggested[column] = drafted;
    const stored = submitted[formName as keyof AddLexiconEntryInput];
    (drafted === stored ? acceptedUnchanged : changedByAdmin).push(column);
  }
  return {
    nl_prefill: {
      source: "copilot_draft",
      text: prefill.text,
      ...(prefill.model ? { model: prefill.model } : {}),
      suggested,
      accepted_unchanged: acceptedUnchanged,
      changed_by_admin: changedByAdmin,
    },
  };
}

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

// The number of columns the detail row has to span. One constant so a new
// column cannot silently leave the panel misaligned.
const COLUMN_COUNT = 13;

// 0.0.5 S26 (FR-31). The score is an ORDINAL in [-0.5, 1.0], not a percentage,
// so it renders to two places with no % sign and never alone: `scope` and
// `basis` come off the server payload and are shown verbatim, because they are
// what stops "0.63" from reading as "this entry is 63% effective everywhere".
function score(health: LexiconEntryHealth | null): string {
  return health === null ? "—" : health.score.toFixed(2);
}

// A rate with no denominator is a count wearing a percentage sign, so every rate
// renders WITH its denominator, and an unscored leg renders "not scored" -- never
// 0%, which reads as a perfect or a terrible result depending on the leg.
function rate(leg: LexiconHealthLeg): string {
  if (leg.rate === null) {
    return leg.undetermined > 0
      ? `not scored (${leg.undetermined} undetermined)`
      : "not scored";
  }
  return `${Math.round(leg.rate * 100)}% of ${leg.determinate}`;
}

function HealthDetail({ health }: { health: LexiconEntryHealth | null }) {
  if (health === null) {
    return (
      <p style={{ margin: "0.15rem 0" }}>
        No effectiveness has been computed for this entry yet — the scheduled
        judge job and the injection ledger both have to have run.
      </p>
    );
  }
  return (
    <>
      <ul style={{ margin: "0.15rem 0", paddingLeft: "1.1rem" }}>
        <li>
          Usage: {health.usage.hits} deterministic application
          {health.usage.hits === 1 ? "" : "s"} + {health.usage.injections} prompt
          injection{health.usage.injections === 1 ? "" : "s"} (counts toward the
          score up to {health.usage.saturation})
        </li>
        <li>Honored: {rate(health.honored)}</li>
        <li>Misapplied: {rate(health.misapplied)}</li>
        <li>Stale: {rate(health.stale)}</li>
      </ul>
      <p style={{ margin: 0, fontSize: "0.75rem", color: "#555" }}>
        {health.scope}
      </p>
      <p style={{ margin: 0, fontSize: "0.75rem", color: "#555" }}>
        {health.basis}
      </p>
    </>
  );
}

export type LexiconConsoleViewProps = {
  entries: LexiconEntry[];
  loading: boolean;
  error: string | null;
  busyId: string | null;
  rowErrors: Record<string, string>;
  addError: string | null;
  statusFilter: LexiconStatus | "all";
  lexiconVersion: string | null;
  onStatusFilter: (status: LexiconStatus | "all") => void;
  onDecide: (entry: LexiconEntry, decision: "confirm" | "reject" | "retire") => void;
  onEdit: (entry: LexiconEntry, canonicalForm: string) => void;
  onAdd: (input: AddLexiconEntryInput) => Promise<boolean> | void;
  // FR-24. Resolves to the copilot's draft, or null when the call itself failed
  // (the container has already put that in `draftError`). A draft that came back
  // `drafted: false` is NOT null — it is an answer, and it carries its reason.
  onDraft: (text: string) => Promise<LexiconDraft | null>;
  draftError: string | null;
};

// The detail surface the Goal asks for ("CRUD + detail surface"). `evidence` and
// `proposerContext` are WHY a mapping was proposed; without them in front of the
// admin, approving a proposal an agent captured from a customer conversation is
// rubber-stamping, and the governance model is "a human decides, with the
// evidence in front of them".
//
// It renders as the row immediately BELOW the entry, so the decision controls
// and the evidence are on screen together -- never one navigation away -- and it
// is open by default on a `proposed` row, which is the row actually being
// decided. A duplicate set of buttons down here would give two controls the same
// accessible name for no gain.
function EntryDetail({ entry }: { entry: LexiconEntry }) {
  return (
    <td
      colSpan={COLUMN_COUNT}
      style={{ padding: "0 1rem 0.75rem 1.5rem", borderBottom: "1px solid #eee" }}
    >
      <div style={{ fontWeight: 600 }}>Evidence</div>
      <p style={{ margin: "0.15rem 0", whiteSpace: "pre-wrap" }}>
        {entry.evidence ?? "No evidence was captured with this entry."}
      </p>
      <p style={{ margin: 0, fontSize: "0.75rem", color: "#555" }}>
        {entry.piiRedacted
          ? "The write scan removed a PII span from this text before it was stored."
          : "The write scan removed no span from this text — see the note below the table for why that is not the same as “no PII here”."}
      </p>
      <div style={{ fontWeight: 600, marginTop: "0.5rem" }}>Proposer context</div>
      {entry.proposerContext ? (
        <pre style={{ margin: "0.15rem 0", fontSize: "0.8rem" }}>
          {JSON.stringify(entry.proposerContext, null, 2)}
        </pre>
      ) : (
        <p style={{ margin: "0.15rem 0" }}>
          No proposer context was captured with this entry.
        </p>
      )}
      <div style={{ fontWeight: 600, marginTop: "0.5rem" }}>Entry health</div>
      <HealthDetail health={entry.health} />
    </td>
  );
}

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
  const [showDetail, setShowDetail] = useState(entry.status === "proposed");
  const busy = busyId === entry.id;
  const editable = entry.status === "proposed" || entry.status === "confirmed";
  // An edit deliberately does NOT re-stamp the decider -- doing so would put a
  // `decided_at` on a still-`proposed` row -- so this column can otherwise read
  // "A" while the content is B's, the same misleading attribution D20 exists to
  // prevent. `updated_at` past `decided_at` IS "changed after it was decided";
  // the audit log names who, and this marker is what tells a supervisor to go
  // look. (No re-stamp; see the ruling in the Postgres handler's docstring.)
  const editedAfterDecision =
    entry.updatedAt !== null && entry.updatedAt > (entry.decidedAt ?? entry.createdAt);

  return (
    <>
      <tr>
        <td style={td}>
          <button
            type="button"
            aria-label={`Evidence for ${entry.surfaceForm}`}
            aria-expanded={showDetail}
            onClick={() => setShowDetail((open) => !open)}
          >
            {showDetail ? "▾" : "▸"}
          </button>
        </td>
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
        <td style={td}>
          {entry.deciderAccountId ?? "—"}
          {editedAfterDecision ? (
            <>
              {" "}
              <span
                style={{ color: "#7a4b00" }}
                title={
                  "The mapping was changed after this decision, so the content " +
                  "may not be the deciderʼs. An edit deliberately does not " +
                  "re-stamp the decider (that would date a decision that never " +
                  "happened); the audit log records who edited it."
                }
              >
                (edited {formatTime(entry.updatedAt)})
              </span>
            </>
          ) : null}
        </td>
        <td style={td}>{entry.hitCount}</td>
        <td style={td}>
          <span
            title={
              entry.health === null
                ? "No effectiveness computed yet."
                : `${entry.health.scope} ${entry.health.basis}`
            }
          >
            {score(entry.health)}
          </span>
        </td>
        <td style={td}>{entry.piiRedacted ? "Scrubbed" : "None removed"}</td>
        <td style={td}>{formatTime(entry.createdAt)}</td>
        <td style={td}>
          <span
            style={{ display: "inline-flex", flexDirection: "column", gap: "0.25rem" }}
          >
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
      {showDetail ? (
        <tr>
          <EntryDetail entry={entry} />
        </tr>
      ) : null}
    </>
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
  lexiconVersion,
  onStatusFilter,
  onDecide,
  onEdit,
  onAdd,
  onDraft,
  draftError,
}: LexiconConsoleViewProps) {
  const [domain, setDomain] = useState("");
  const [entryKind, setEntryKind] = useState<LexiconEntryKind>("alias");
  const [surfaceForm, setSurfaceForm] = useState("");
  const [canonicalForm, setCanonicalForm] = useState("");
  const [nlText, setNlText] = useState("");
  const [prefill, setPrefill] = useState<NlPrefill | null>(null);
  const [draftNotice, setDraftNotice] = useState<string | null>(null);
  const healthScope = entries.find((e) => e.health !== null)?.health?.scope ?? null;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const input: AddLexiconEntryInput = {
      domain,
      entryKind,
      surfaceForm,
      canonicalForm,
    };
    const proposerContext = nlPrefillProvenance(prefill, input);
    const ok = await onAdd(proposerContext ? { ...input, proposerContext } : input);
    if (ok) {
      setSurfaceForm("");
      setCanonicalForm("");
      // The prefill belongs to the entry that just landed. Keeping it would
      // attach one sentence's provenance to the NEXT entry the admin types,
      // which is a worse lie than having no record at all.
      setPrefill(null);
      setNlText("");
      setDraftNotice(null);
    }
  }

  // FR-24. Whatever comes back, the form is left usable: a draft fills the
  // fields it could read and says so; a refusal says why and touches nothing.
  async function handleDraft() {
    setDraftNotice(null);
    const draft = await onDraft(nlText);
    if (!draft) return;
    if (!draft.drafted || !draft.fields) {
      setPrefill(null);
      setDraftNotice(draft.reason ?? "The copilot could not draft an entry from that.");
      return;
    }
    const fields = draft.fields;
    if (fields.domain) setDomain(fields.domain);
    if (fields.entryKind) setEntryKind(fields.entryKind as LexiconEntryKind);
    if (fields.surfaceForm) setSurfaceForm(fields.surfaceForm);
    if (fields.canonicalForm) setCanonicalForm(fields.canonicalForm);
    setPrefill({ text: nlText, fields, model: draft.model });
    setDraftNotice(
      "The copilot filled these in — read them, change anything that is wrong, " +
        "then press Add. Nothing is stored until you do.",
    );
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
                  <th style={th}>
                    <span style={{ fontWeight: 400, fontSize: "0.75rem" }}>Why</span>
                  </th>
                  <th style={th}>Domain</th>
                  <th style={th}>Kind</th>
                  <th style={th}>Surface form</th>
                  <th style={th}>Canonical form</th>
                  <th style={th}>Status</th>
                  <th style={th}>Provenance</th>
                  <th style={th}>Decider</th>
                  <th style={th}>Hits</th>
                  <th style={th}>Health</th>
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
            {/* The Health column's caveats, taken from the SERVER's own payload
                rather than restated here, so the table footnote and the per-row
                detail can never claim different scopes. A tooltip alone would
                not do: the caveat has to be readable without hovering. */}
            {healthScope ? (
              <p style={{ fontSize: "0.8rem", color: "#555", margin: 0 }}>
                Health: higher is better, on a −0.50 to 1.00 scale — usage,
                honored, misapplied and stale in one number. {healthScope}
              </p>
            ) : null}
            {lexiconVersion ? (
              <p
                style={{ fontSize: "0.75rem", color: "#666", margin: 0 }}
                title={
                  "The newest updated_at across ALL lexicon entries. Every " +
                  "governed write moves it, so the caches that apply the lexicon " +
                  "can tell in one comparison whether anything changed."
                }
              >
                Lexicon version: {lexiconVersion}
              </p>
            ) : null}
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

        {/* FR-24/US11. Deliberately a separate control from Add: drafting is a
            suggestion and adding is the decision, and one button doing both
            would be the auto-submit this slice's brief puts out of scope. */}
        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="lexicon-nl" style={{ display: "block", fontWeight: 600 }}>
            Describe it in your own words (optional)
          </label>
          <input
            id="lexicon-nl"
            value={nlText}
            placeholder="TOEE 也叫拓意"
            onChange={(e) => setNlText(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
          <button
            type="button"
            disabled={busyId === DRAFT_BUSY_ID || nlText.trim().length === 0}
            onClick={() => void handleDraft()}
            style={{ marginTop: "0.35rem" }}
          >
            {busyId === DRAFT_BUSY_ID ? "Drafting…" : "Draft with the copilot"}
          </button>
          {draftNotice ? (
            <p style={{ fontSize: "0.8rem", color: "#555", margin: "0.35rem 0 0" }}>
              {draftNotice}
            </p>
          ) : null}
          {draftError ? (
            <p role="alert" style={{ ...alert, fontSize: "0.8rem", margin: "0.35rem 0 0" }}>
              {draftError}
            </p>
          ) : null}
          {prefill ? (
            <p style={{ fontSize: "0.75rem", color: "#555", margin: "0.35rem 0 0" }}>
              What you add will record that the copilot drafted it from this
              sentence, and which fields you left exactly as it wrote them.
            </p>
          ) : null}
        </div>

        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="lexicon-domain" style={{ display: "block", fontWeight: 600 }}>
            Domain
          </label>
          {/* `required` is the browser's own guard: a blank field never becomes
              a request at all. The BFF still 400s a blank field for callers that
              are not this form (review finding E). */}
          <input
            id="lexicon-domain"
            required
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
            required
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
            required
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
  const [draftError, setDraftError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<LexiconStatus | "all">("all");
  const [lexiconVersion, setLexiconVersion] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const listing = await listLexiconEntries(
        statusFilter === "all" ? {} : { status: statusFilter },
      );
      setEntries(listing.entries ?? []);
      setLexiconVersion(listing.lexiconVersion ?? null);
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

  // FR-24. A failed draft never blocks the form: the error is reported beside
  // the draft box and every field stays exactly as the admin left it.
  async function handleDraft(text: string): Promise<LexiconDraft | null> {
    setBusyId(DRAFT_BUSY_ID);
    setDraftError(null);
    try {
      return await draftLexiconEntry(text);
    } catch (e) {
      setDraftError(message(e, "The copilot could not be reached — type the entry yourself"));
      return null;
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
      draftError={draftError}
      statusFilter={statusFilter}
      lexiconVersion={lexiconVersion}
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
      onDraft={handleDraft}
    />
  );
}
