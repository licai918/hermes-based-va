// The four v1 Customer Memory preference slots (ADR-0111). Open-ended keys are
// not allowed: only these slots may be written, cleared, or read. Python keeps
// its own authoritative copy at
// hermes/toee_hermes/drivers/mock/memory.py::MEMORY_PREFERENCE_SLOTS -- update
// both lists together so the two runtimes can't silently drift.
export type MemoryPreferenceSlot =
  | "contact_time_preference"
  | "channel_preference"
  | "delivery_habit_note"
  | "communication_style_note";

// Single source of truth for the four v1 slots on the TS side (S07/S09, FR-6/
// FR-7): the workbench and the domain-adapters mock driver both import this
// rather than hand-copying a second literal, so a fifth slot added here
// propagates instead of silently drifting between the two lists.
export const MEMORY_PREFERENCE_SLOTS: readonly MemoryPreferenceSlot[] = [
  "contact_time_preference",
  "channel_preference",
  "delivery_habit_note",
  "communication_style_note",
];
