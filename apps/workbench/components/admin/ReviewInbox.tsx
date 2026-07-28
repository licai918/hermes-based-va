"use client";

// The unified review inbox (0.0.5 S15, FR-22 / US4 / US9): ONE queue holding
// every pending memory decision -- L6 proposals, L7 proposals, and the
// `review_item` store's graduation / blast-radius / persona-review /
// retirement-candidate items. Layer badge, the decisions each kind's own layer
// can honour, and Re-classify for a mis-filed proposal.
//
// Split into a pure View and a fetching container, the LexiconConsole shape: the
// container owns the BFF calls, a decided row leaves the queue (it is a QUEUE --
// the per-layer consoles are where history is read), and a failed decision
// leaves the row actionable to retry with its error inline.
import { useCallback, useEffect, useState } from "react";
import {
  decideInboxItem,
  listInbox,
  reclassifyInboxItem,
  type InboxItem,
} from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "0.25rem 1rem 0.25rem 0",
  borderBottom: "1px solid #ccc",
};
const td: React.CSSProperties = {
  padding: "0.35rem 1rem 0.35rem 0",
  verticalAlign: "top",
};
const badge: React.CSSProperties = {
  border: "1px solid #999",
  borderRadius: "0.25rem",
  padding: "0 0.3rem",
  fontSize: "0.75rem",
};

const DECISION_LABELS: Record<string, string> = {
  accept: "Accept",
  reject: "Reject",
  acknowledge: "Acknowledge",
  dismiss: "Dismiss",
};

// D8's two reserved keys, rendered as visually distinct blocks so an admin can
// tell a write-time heuristic (S13) from a copilot triage note (S16) rather than
// reading one merged blob.
const ANNOTATION_LABELS: Record<string, string> = {
  heuristic: "Advisory",
  copilot: "Triage",
};

export type ReclassifyDraft = {
  domain: string;
  entryKind: string;
  surfaceForm: string;
  canonicalForm: string;
};

export const EMPTY_RECLASSIFY: ReclassifyDraft = {
  domain: "",
  entryKind: "alias",
  surfaceForm: "",
  canonicalForm: "",
};

export function ReviewInboxView({
  items,
  count,
  loading,
  error,
  busyId,
  rowErrors,
  reclassifyId,
  onDecide,
  onOpenReclassify,
  onReclassify,
}: {
  items: InboxItem[];
  count: number;
  loading: boolean;
  error: string | null;
  busyId: string | null;
  rowErrors: Record<string, string>;
  reclassifyId: string | null;
  onDecide: (item: InboxItem, decision: string) => void;
  onOpenReclassify: (item: InboxItem | null) => void;
  onReclassify: (item: InboxItem, draft: ReclassifyDraft) => void;
}) {
  const [draft, setDraft] = useState<ReclassifyDraft>(EMPTY_RECLASSIFY);

  return (
    <section
      aria-label="Review inbox"
      style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
    >
      <p>
        <strong data-testid="inbox-count">{count}</strong> pending
        {count === 1 ? " decision" : " decisions"}
      </p>
      {loading ? <p>Loading…</p> : null}
      {error ? (
        <p role="alert" style={{ color: "#8a1c1c" }}>
          {error}
        </p>
      ) : null}
      {!loading && !error ? (
        items.length > 0 ? (
          <table style={{ borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={th}>Layer</th>
                <th style={th}>Kind</th>
                <th style={th}>Subject</th>
                <th style={th}>Detail</th>
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={`${i.kind}:${i.id}`}>
                  <td style={td}>
                    {/* Absent where the kind does not determine it -- see
                        LAYER_BY_KIND in lib/bff/admin/review-inbox.ts. */}
                    {i.layer ? <span style={badge}>{i.layer}</span> : "—"}
                  </td>
                  <td style={td}>
                    <span style={badge}>{i.kind}</span>
                  </td>
                  <td style={td}>{i.subject}</td>
                  <td style={td}>
                    {i.detail ?? "—"}
                    {i.annotations
                      ? Object.entries(i.annotations).map(([key, value]) => (
                          <p
                            key={key}
                            data-testid={`annotation-${key}`}
                            style={{
                              margin: "0.25rem 0 0",
                              fontSize: "0.8rem",
                              borderLeft: "3px solid #999",
                              paddingLeft: "0.4rem",
                            }}
                          >
                            <strong>{ANNOTATION_LABELS[key] ?? key}: </strong>
                            {typeof value === "string" ? value : JSON.stringify(value)}
                          </p>
                        ))
                      : null}
                  </td>
                  <td style={td}>
                    <span
                      style={{
                        display: "inline-flex",
                        flexDirection: "column",
                        gap: "0.25rem",
                      }}
                    >
                      <span style={{ display: "inline-flex", gap: "0.4rem" }}>
                        {i.decisions.map((decision) => (
                          <button
                            key={decision}
                            type="button"
                            aria-label={`${DECISION_LABELS[decision] ?? decision} ${i.id}`}
                            disabled={busyId === i.id}
                            onClick={() => onDecide(i, decision)}
                          >
                            {DECISION_LABELS[decision] ?? decision}
                          </button>
                        ))}
                        {i.reclassifiable ? (
                          <button
                            type="button"
                            aria-label={`Re-classify ${i.id}`}
                            disabled={busyId === i.id}
                            onClick={() => {
                              setDraft(EMPTY_RECLASSIFY);
                              onOpenReclassify(reclassifyId === i.id ? null : i);
                            }}
                          >
                            Re-classify
                          </button>
                        ) : null}
                      </span>
                      {reclassifyId === i.id ? (
                        <form
                          aria-label={`Re-classify ${i.id} to the lexicon`}
                          onSubmit={(e) => {
                            e.preventDefault();
                            onReclassify(i, draft);
                          }}
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: "0.2rem",
                          }}
                        >
                          <label>
                            Domain
                            <input
                              value={draft.domain}
                              onChange={(e) =>
                                setDraft({ ...draft, domain: e.target.value })
                              }
                            />
                          </label>
                          <label>
                            Kind
                            <select
                              value={draft.entryKind}
                              onChange={(e) =>
                                setDraft({ ...draft, entryKind: e.target.value })
                              }
                            >
                              <option value="alias">alias</option>
                              <option value="normalizer">normalizer</option>
                              <option value="default_rule">default_rule</option>
                            </select>
                          </label>
                          <label>
                            Surface form
                            <input
                              value={draft.surfaceForm}
                              onChange={(e) =>
                                setDraft({ ...draft, surfaceForm: e.target.value })
                              }
                            />
                          </label>
                          <label>
                            Canonical form
                            <input
                              value={draft.canonicalForm}
                              onChange={(e) =>
                                setDraft({ ...draft, canonicalForm: e.target.value })
                              }
                            />
                          </label>
                          <button type="submit">Move to lexicon queue</button>
                        </form>
                      ) : null}
                      {rowErrors[i.id] ? (
                        <span
                          role="alert"
                          style={{ color: "#8a1c1c", fontSize: "0.8rem" }}
                        >
                          {rowErrors[i.id]}
                        </span>
                      ) : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p>Nothing waiting for review.</p>
        )
      ) : null}
    </section>
  );
}

export function ReviewInbox() {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [reclassifyId, setReclassifyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listInbox();
      setItems(result.items);
      setCount(result.count);
    } catch (e) {
      setItems([]);
      setError(e instanceof ApiError ? e.message : "Failed to load the review inbox");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function clearRowError(id: string) {
    setRowErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  async function run(item: InboxItem, work: () => Promise<unknown>, label: string) {
    setBusyId(item.id);
    clearRowError(item.id);
    try {
      await work();
      // A decided item leaves the QUEUE. Re-reading is the honest refresh: a
      // Re-classify adds an L7 proposal that must now appear, so patching the
      // one row locally would leave the badge and the list disagreeing.
      setReclassifyId(null);
      await load();
    } catch (e) {
      setRowErrors((prev) => ({
        ...prev,
        [item.id]: e instanceof ApiError ? e.message : `Failed to ${label} this item`,
      }));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <ReviewInboxView
      items={items}
      count={count}
      loading={loading}
      error={error}
      busyId={busyId}
      rowErrors={rowErrors}
      reclassifyId={reclassifyId}
      onDecide={(item, decision) =>
        void run(item, () => decideInboxItem(item.kind, item.id, decision), decision)
      }
      onOpenReclassify={(item) => setReclassifyId(item ? item.id : null)}
      onReclassify={(item, draft) =>
        void run(
          item,
          () => reclassifyInboxItem({ sourceKind: item.kind, id: item.id, ...draft }),
          "re-classify",
        )
      }
    />
  );
}
