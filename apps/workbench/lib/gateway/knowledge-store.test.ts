import { describe, expect, it, beforeEach } from "vitest";
import {
  REQUIRED_SLOT_IDS,
  createInMemoryKnowledgeStore,
  type KnowledgeStore,
} from "./knowledge-store";

let store: KnowledgeStore;
beforeEach(() => {
  store = createInMemoryKnowledgeStore();
});

describe("knowledge store seed", () => {
  it("exposes the six required operational policy slots (ADR-0003)", () => {
    const ids = store.listSlots().map((s) => s.slotId);
    expect(ids).toEqual([...REQUIRED_SLOT_IDS]);
    expect(ids).toHaveLength(6);
  });
});

describe("saveDraft", () => {
  it("moves an empty slot to draft and stores the text", () => {
    const slot = store.saveDraft("returns-exchanges", { draftText: "30-day returns." });
    expect(slot?.status).toBe("draft");
    expect(slot?.draftText).toBe("30-day returns.");
  });

  it("returns undefined for an unknown slot", () => {
    expect(store.saveDraft("nope", { draftText: "x" })).toBeUndefined();
  });
});

describe("submitForEval", () => {
  it("moves a draft slot to pending_eval", () => {
    store.saveDraft("returns-exchanges", { draftText: "30-day returns." });
    const result = store.submitForEval("returns-exchanges");
    expect(result).toEqual({ ok: true, slot: expect.objectContaining({ status: "pending_eval" }) });
  });

  it("refuses to submit a slot with no draft", () => {
    expect(store.submitForEval("returns-exchanges")).toEqual({ ok: false, reason: "no_draft" });
  });

  it("reports not_found for an unknown slot", () => {
    expect(store.submitForEval("nope")).toEqual({ ok: false, reason: "not_found" });
  });
});

describe("rollbackPublished", () => {
  it("restores the previous published version when one exists", () => {
    const result = store.rollbackPublished("business-hours");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.slot.status).toBe("published");
    }
  });

  it("refuses rollback when there is no previous version", () => {
    expect(store.rollbackPublished("returns-exchanges")).toEqual({
      ok: false,
      reason: "no_previous_version",
    });
  });
});
