"use client";

// KnowledgeOps master-detail console (ADR-0087): the six Required Operational
// Policy Slots (ADR-0003) on the left, an authoring editor on the right. Split
// into a pure presentational view (props in, callbacks out) and a thin fetching
// container so the gating/render logic is testable without a network.
import { useCallback, useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { useErrorBanner } from "@/components/shell/error-banner";
import {
  listSlots,
  rollbackSlot,
  saveDraft,
  submitSlot,
} from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { PolicySlot, SlotStatus } from "@/lib/gateway/knowledge-store";

type Editor = { draftText: string; owner: string; reviewDate: string };

const STATUS_LABELS: Record<SlotStatus, string> = {
  empty: "Empty",
  draft: "Draft",
  pending_eval: "Pending eval",
  published: "Published",
  gap: "Gap",
};

const STATUS_COLORS: Record<SlotStatus, string> = {
  empty: "#6b7280",
  draft: "#b45309",
  pending_eval: "#1d4ed8",
  published: "#15803d",
  gap: "#b91c1c",
};

function SlotStatusBadge({ status }: { status: SlotStatus }) {
  return (
    <span
      style={{
        fontSize: "0.6875rem",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.03em",
        color: STATUS_COLORS[status],
        border: `1px solid ${STATUS_COLORS[status]}`,
        borderRadius: "999px",
        padding: "0.05rem 0.5rem",
        whiteSpace: "nowrap",
      }}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

export type KnowledgeConsoleViewProps = {
  slots: PolicySlot[];
  selectedId: string | null;
  editor: Editor;
  busy: boolean;
  error: string | null;
  onSelect: (slotId: string) => void;
  onEditorChange: (patch: Partial<Editor>) => void;
  onSave: () => void;
  onSubmit: () => void;
  onRollback: () => void;
};

const fieldStyle = { display: "block", marginBottom: "0.75rem" } as const;
const labelStyle = { display: "block", fontWeight: 600, marginBottom: "0.25rem" } as const;
const controlStyle = { width: "100%", boxSizing: "border-box" } as const;

export function KnowledgeConsoleView({
  slots,
  selectedId,
  editor,
  busy,
  error,
  onSelect,
  onEditorChange,
  onSave,
  onSubmit,
  onRollback,
}: KnowledgeConsoleViewProps) {
  const selected = selectedId
    ? (slots.find((s) => s.slotId === selectedId) ?? null)
    : null;

  return (
    <div style={{ display: "flex", gap: "1.5rem", alignItems: "flex-start" }}>
      <nav aria-label="Policy slots" style={{ width: "18rem", flexShrink: 0 }}>
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {slots.map((s) => {
            const active = s.slotId === selectedId;
            return (
              <li key={s.slotId}>
                <button
                  type="button"
                  onClick={() => onSelect(s.slotId)}
                  aria-current={active}
                  style={{
                    display: "flex",
                    gap: "0.5rem",
                    alignItems: "center",
                    width: "100%",
                    textAlign: "left",
                    padding: "0.5rem 0.625rem",
                    marginBottom: "0.25rem",
                    border: "1px solid #e2e2e2",
                    borderRadius: "0.375rem",
                    background: active ? "#eef2ff" : "#fff",
                    cursor: "pointer",
                  }}
                >
                  <span style={{ flex: 1 }}>{s.title}</span>
                  <SlotStatusBadge status={s.status} />
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <section style={{ flex: 1, minWidth: 0 }}>
        {selected ? (
          <>
            <div
              style={{
                display: "flex",
                gap: "0.75rem",
                alignItems: "center",
                marginBottom: "0.75rem",
              }}
            >
              <h2 style={{ margin: 0, fontSize: "1.125rem" }}>{selected.title}</h2>
              <SlotStatusBadge status={selected.status} />
            </div>

            {selected.hasGapPrompt ? (
              <p style={{ color: "#b91c1c", marginTop: 0 }}>
                No policy captured yet — draft the standard guidance for this slot.
              </p>
            ) : null}

            {selected.publishedText ? (
              <div style={{ marginBottom: "0.75rem" }}>
                <h3 style={{ margin: "0 0 0.25rem", fontSize: "0.8125rem", opacity: 0.7 }}>
                  Published version
                </h3>
                <p style={{ margin: 0 }}>{selected.publishedText}</p>
              </div>
            ) : null}

            <div style={fieldStyle}>
              <label htmlFor="slot-draft" style={labelStyle}>
                Draft text
              </label>
              <textarea
                id="slot-draft"
                rows={6}
                value={editor.draftText}
                onChange={(e) => onEditorChange({ draftText: e.target.value })}
                style={controlStyle}
              />
            </div>

            <div style={fieldStyle}>
              <label htmlFor="slot-owner" style={labelStyle}>
                Owner
              </label>
              <input
                id="slot-owner"
                value={editor.owner}
                onChange={(e) => onEditorChange({ owner: e.target.value })}
                style={controlStyle}
              />
            </div>

            <div style={fieldStyle}>
              <label htmlFor="slot-review" style={labelStyle}>
                Review date
              </label>
              <input
                id="slot-review"
                type="date"
                value={editor.reviewDate}
                onChange={(e) => onEditorChange({ reviewDate: e.target.value })}
                style={controlStyle}
              />
            </div>

            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <button type="button" onClick={onSave} disabled={busy}>
                Save draft
              </button>
              <button
                type="button"
                onClick={onSubmit}
                disabled={busy || selected.status !== "draft"}
              >
                Submit for eval
              </button>
              {selected.status === "published" ? (
                <button type="button" onClick={onRollback} disabled={busy}>
                  Rollback
                </button>
              ) : null}
            </div>

            {error ? (
              <p role="alert" style={{ color: "#8a1c1c", marginBottom: 0 }}>
                {error}
              </p>
            ) : null}
          </>
        ) : (
          <EmptyState
            title="Select a policy slot"
            description="Choose a slot from the list to view or edit its policy text."
          />
        )}
      </section>
    </div>
  );
}

function editorFor(slot: PolicySlot | undefined): Editor {
  return {
    draftText: slot?.draftText ?? "",
    owner: slot?.owner ?? "",
    reviewDate: slot?.reviewDate ?? "",
  };
}

export function KnowledgeConsole() {
  const { showError } = useErrorBanner();
  const [slots, setSlots] = useState<PolicySlot[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editor, setEditor] = useState<Editor>({
    draftText: "",
    owner: "",
    reviewDate: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (keepId: string | null) => {
    const next = await listSlots();
    setSlots(next);
    if (keepId) setEditor(editorFor(next.find((s) => s.slotId === keepId)));
  }, []);

  useEffect(() => {
    listSlots()
      .then(setSlots)
      .catch((e) => {
        const msg = e instanceof ApiError ? e.message : "Failed to load policy slots";
        setError(msg);
        showError(msg);
      });
  }, [showError]);

  function handleSelect(slotId: string) {
    setSelectedId(slotId);
    setEditor(editorFor(slots.find((s) => s.slotId === slotId)));
    setError(null);
  }

  async function runAction(slotId: string, action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await reload(slotId);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Action failed";
      setError(msg);
      showError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <KnowledgeConsoleView
      slots={slots}
      selectedId={selectedId}
      editor={editor}
      busy={busy}
      error={error}
      onSelect={handleSelect}
      onEditorChange={(patch) => setEditor((prev) => ({ ...prev, ...patch }))}
      onSave={() =>
        selectedId && runAction(selectedId, () => saveDraft(selectedId, editor))
      }
      onSubmit={() => selectedId && runAction(selectedId, () => submitSlot(selectedId))}
      onRollback={() =>
        selectedId && runAction(selectedId, () => rollbackSlot(selectedId))
      }
    />
  );
}
