// S07 (FR-6, formerly S09/FR-7): the four v1 Customer Memory preference slots
// must have exactly one source of truth. `packages/shared/src/memory.ts` owns
// the list; the workbench re-exports it rather than hand-copying a second
// literal that could silently drift (e.g. a fifth slot added in one place only).
import { describe, expect, it } from "vitest";
import { MEMORY_PREFERENCE_SLOTS } from "@toee/shared";
import { PREFERENCE_SLOTS } from "./types";

describe("PREFERENCE_SLOTS single-source (S07, FR-6)", () => {
  it("is the same array instance exported by @toee/shared, not a re-declared copy", () => {
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
