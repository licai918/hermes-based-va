"use client";

// Customer Preferences panel (ADR-0111/0114, PAC-4 S18): the case's 4 Customer
// Memory preference slots, read-only display with an inline correct/clear editor
// per slot -- mirrors the contact-reason inline editor in ThreadContext.tsx
// (edit/save/cancel), plus an inline confirm step before a clear takes effect.
// Presentational: every mutation is reported through onUpsert/onClear so the
// container (CopilotDashboard) owns the BFF calls and refetch; this makes no
// network calls itself. Every copilot role may view; ADR-0111 grants
// correct/clear to Customer Service Rep and above, and WORKBENCH_ROLES has no
// role below rep, so every signed-in role already qualifies -- there is no
// non-eligible role to gate out.
import { useState } from "react";
import type {
  CustomerPreferences as CustomerPreferencesData,
  MemoryPreferenceSlot,
} from "@/lib/gateway/types";
import { PREFERENCE_SLOTS } from "@/lib/gateway/types";

const SLOT_LABELS: Record<MemoryPreferenceSlot, string> = {
  contact_time_preference: "Preferred contact time",
  channel_preference: "Preferred channel",
  delivery_habit_note: "Delivery habit note",
  communication_style_note: "Communication style",
};

const META_ITEM: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "0.1rem" };
const META_LABEL: React.CSSProperties = { fontSize: "0.7rem", textTransform: "uppercase", color: "#777" };

export function CustomerPreferences({
  preferences,
  onUpsert,
  onClear,
}: {
  preferences: CustomerPreferencesData;
  onUpsert: (slot: MemoryPreferenceSlot, value: string) => void;
  onClear: (slot: MemoryPreferenceSlot) => void;
}) {
  const [editingSlot, setEditingSlot] = useState<MemoryPreferenceSlot | null>(null);
  const [draft, setDraft] = useState("");
  const [confirmClearSlot, setConfirmClearSlot] = useState<MemoryPreferenceSlot | null>(null);

  function startEdit(slot: MemoryPreferenceSlot, value: string | undefined) {
    setConfirmClearSlot(null);
    setDraft(value ?? "");
    setEditingSlot(slot);
  }

  function save(slot: MemoryPreferenceSlot) {
    const next = draft.trim();
    if (next.length > 0) onUpsert(slot, next);
    setEditingSlot(null);
  }

  function startClear(slot: MemoryPreferenceSlot) {
    setEditingSlot(null);
    setConfirmClearSlot(slot);
  }

  function confirmClear(slot: MemoryPreferenceSlot) {
    onClear(slot);
    setConfirmClearSlot(null);
  }

  return (
    <section
      aria-label="Customer preferences"
      style={{ display: "flex", flexDirection: "column", gap: "0.5rem", padding: "0.6rem 0.75rem" }}
    >
      <h2 style={{ margin: 0, fontSize: "0.85rem" }}>Customer preferences</h2>
      {PREFERENCE_SLOTS.map((slot) => {
        const label = SLOT_LABELS[slot];
        const value = preferences[slot];
        return (
          <div key={slot} style={META_ITEM}>
            <span style={META_LABEL}>{label}</span>
            {editingSlot === slot ? (
              <span style={{ display: "inline-flex", gap: "0.3rem" }}>
                <input aria-label={label} value={draft} onChange={(e) => setDraft(e.target.value)} />
                <button type="button" onClick={() => save(slot)}>
                  Save
                </button>
                <button type="button" onClick={() => setEditingSlot(null)}>
                  Cancel
                </button>
              </span>
            ) : confirmClearSlot === slot ? (
              <span style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
                Clear this preference?
                <button type="button" onClick={() => confirmClear(slot)}>
                  Confirm clear
                </button>
                <button type="button" onClick={() => setConfirmClearSlot(null)}>
                  Cancel
                </button>
              </span>
            ) : (
              <span style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
                {value ?? "Not set"}
                <button type="button" aria-label={`Edit ${label}`} onClick={() => startEdit(slot, value)}>
                  Edit
                </button>
                {value ? (
                  <button type="button" aria-label={`Clear ${label}`} onClick={() => startClear(slot)}>
                    Clear
                  </button>
                ) : null}
              </span>
            )}
          </div>
        );
      })}
    </section>
  );
}
