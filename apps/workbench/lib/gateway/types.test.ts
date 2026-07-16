// S09 (FR-7): the four v1 Customer Memory preference slots must have exactly one
// source of truth. `packages/domain-adapters/src/mock/memory.ts` owns the list;
// the workbench re-exports it rather than hand-copying a second literal that
// could silently drift (e.g. a fifth slot added in one place only).
import { describe, expect, it } from "vitest";
import { MEMORY_PREFERENCE_SLOTS } from "@toee/domain-adapters";
import { PREFERENCE_SLOTS } from "./types";

describe("PREFERENCE_SLOTS single-source (S09, FR-7)", () => {
  it("is the same array instance exported by @toee/domain-adapters, not a re-declared copy", () => {
    expect(PREFERENCE_SLOTS).toBe(MEMORY_PREFERENCE_SLOTS);
  });

  it("holds exactly the four v1 slots (ADR-0111)", () => {
    expect(PREFERENCE_SLOTS).toEqual([
      "contact_time_preference",
      "channel_preference",
      "delivery_habit_note",
      "communication_style_note",
    ]);
  });
});
