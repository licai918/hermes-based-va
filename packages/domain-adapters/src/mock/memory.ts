import { ToolDriverError } from "../errors";
import type { ToolExecutionContext } from "../tool-gate";
import type { MockHandlerRegistry } from "./mock-driver";

// The four v1 Customer Memory preference slots (ADR-0111). Open-ended keys are
// not allowed: only these slots may be written, cleared, or read.
export type MemoryPreferenceSlot =
  | "contact_time_preference"
  | "channel_preference"
  | "delivery_habit_note"
  | "communication_style_note";

export type CustomerPreferenceSlots = Partial<
  Record<MemoryPreferenceSlot, string>
>;

// Injectable Customer Memory fixtures for `toee_customer_memory`. `preferences`
// is the slot map injected for the active identity binding before a turn runs —
// the mock equivalent of ADR-0113 lightweight injection (a scenario
// `memory_preset`). Default is empty: nothing is remembered until an explicit
// write happens.
export interface MemoryMockData {
  preferences: CustomerPreferenceSlots;
}

export const memoryBaselineData: MemoryMockData = { preferences: {} };

// Single source of truth for the four v1 slots (S09, FR-7): the workbench
// imports this rather than hand-copying a second literal, so a fifth slot
// added here propagates instead of silently drifting between the two lists.
export const MEMORY_PREFERENCE_SLOTS: readonly MemoryPreferenceSlot[] = [
  "contact_time_preference",
  "channel_preference",
  "delivery_habit_note",
  "communication_style_note",
];

function isPreferenceSlot(value: unknown): value is MemoryPreferenceSlot {
  return (
    typeof value === "string" &&
    (MEMORY_PREFERENCE_SLOTS as readonly string[]).includes(value)
  );
}

// Customer Memory binds to the verified `shopifyCustomerId`, else to a
// provisional channel binding (ADR-0112, ADR-0113). The mock keeps a single
// provisional bucket; ambiguous matches never merge in v1, so they are not split
// further here.
function resolveBindingKey(context: ToolExecutionContext): string {
  const identity = context.identity;
  if (identity?.outcome === "verified_customer") {
    return identity.shopifyCustomerId;
  }
  return "provisional";
}

// Resolves the target slot from `key` (the v1 param name) or its `slot` alias.
// Open-ended preference keys are rejected per ADR-0111 rather than silently
// stored, so an inferred or non-v1 write never lands in memory.
function requireSlot(params: Record<string, unknown>): MemoryPreferenceSlot {
  const requested = params.key ?? params.slot;
  if (!isPreferenceSlot(requested)) {
    throw new ToolDriverError(
      "unexpected_error",
      `Customer Memory rejects open-ended preference key "${String(requested)}"; only the four v1 slots are allowed (ADR-0111).`,
    );
  }
  return requested;
}

// Builds `toee_customer_memory` handlers backed by a per-binding preference
// store. Each binding is lazily seeded from the injected baseline so a scenario
// `memory_preset` is honored on first read (ADR-0113), while writes stay isolated
// per identity binding. Writes are explicit-only: the mock never infers or
// fabricates a preference, so eval scenario 26 can assert no inferred upsert.
export function createMemoryMockHandlers(
  data: MemoryMockData = memoryBaselineData,
): MockHandlerRegistry {
  const store = new Map<string, CustomerPreferenceSlots>();

  const slotsFor = (bindingKey: string): CustomerPreferenceSlots => {
    let slots = store.get(bindingKey);
    if (slots === undefined) {
      slots = { ...data.preferences };
      store.set(bindingKey, slots);
    }
    return slots;
  };

  return {
    toee_customer_memory: {
      // Records one explicit preference slot and echoes the stored value
      // (scenario 24). The Tool Gate — not this driver — enforces that the write
      // came from explicit customer language (ADR-0114).
      upsert_preference: (params, context) => {
        const slot = requireSlot(params);
        const value = params.value;
        if (typeof value !== "string") {
          throw new ToolDriverError(
            "unexpected_error",
            "upsert_preference requires a string value.",
          );
        }
        const source = typeof params.source === "string" ? params.source : null;
        const bindingKey = resolveBindingKey(context);
        slotsFor(bindingKey)[slot] = value;
        return { bindingKey, slot, value, source, stored: true };
      },
      // Clears one preference slot and acknowledges the removal.
      clear_preference: (params, context) => {
        const slot = requireSlot(params);
        const bindingKey = resolveBindingKey(context);
        delete slotsFor(bindingKey)[slot];
        return { bindingKey, slot, cleared: true };
      },
      // Returns the current preference slots for the active binding, honoring any
      // injected baseline (scenario 25).
      get_preferences: (_params, context) => {
        const bindingKey = resolveBindingKey(context);
        return { bindingKey, preferences: { ...slotsFor(bindingKey) } };
      },
    },
  };
}

// Default registry wired to the (empty) baseline fixtures.
export const memoryMockHandlers: MockHandlerRegistry =
  createMemoryMockHandlers();
