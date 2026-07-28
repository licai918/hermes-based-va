import { describe, expect, it } from "vitest";
import type { MemoryAuditEntry, MemoryAuditView } from "@/lib/gateway/types";
import { deriveProposalHistory, historyDetail } from "./MemoryAuditConsole";

// S16 (FR-17, audit finding 14): a dismissed proposal writes no slot, so the
// slot list alone can never show it. deriveProposalHistory is the pure
// derivation behind the "Proposal history" section -- accepted = the
// employee_confirmed slots (S15's model: that slot row IS the acceptance
// record, no separate proposal_accepted audit action), dismissed =
// proposal_dismissed history rows. Tested as a pure function, not through
// rendering, since it's the derivation the section renders that matters.

const baseView: MemoryAuditView = {
  slots: [
    {
      slot: "channel_preference",
      value: "sms",
      source: "employee_confirmed",
      actorAccountId: "acct_rep_4",
      evidence: null,
      createdAt: Date.parse("2026-07-05T09:00:00Z"),
      updatedAt: Date.parse("2026-07-05T09:00:00Z"),
    },
    {
      slot: "contact_time_preference",
      value: "mornings",
      source: "customer_explicit",
      actorAccountId: null,
      evidence: "said mornings",
      createdAt: Date.parse("2026-07-01T09:00:00Z"),
      updatedAt: Date.parse("2026-07-01T09:00:00Z"),
    },
  ],
  history: [
    {
      entryId: "audit_1",
      at: Date.parse("2026-07-05T09:05:00Z"),
      actorAccountId: "acct_rep_4",
      actorUsername: "rep_4",
      action: "proposal_dismissed",
      slot: "delivery_habit_note",
      value: "back door",
    },
    {
      entryId: "audit_2",
      at: Date.parse("2026-07-06T09:05:00Z"),
      actorAccountId: "acct_sup_1",
      actorUsername: "sup_1",
      action: "preference_cleared",
      slot: "channel_preference",
    },
  ],
};

describe("deriveProposalHistory", () => {
  it("includes the employee_confirmed slot as an accepted row", () => {
    const rows = deriveProposalHistory(baseView);
    const accepted = rows.find((r) => r.outcome === "accepted");
    expect(accepted).toMatchObject({
      slot: "channel_preference",
      value: "sms",
      decider: "acct_rep_4",
      at: Date.parse("2026-07-05T09:00:00Z"),
    });
  });

  it("includes the proposal_dismissed history row as a dismissed row with its proposed value", () => {
    const rows = deriveProposalHistory(baseView);
    const dismissed = rows.find((r) => r.outcome === "dismissed");
    expect(dismissed).toMatchObject({
      slot: "delivery_habit_note",
      value: "back door",
      decider: "rep_4",
      at: Date.parse("2026-07-05T09:05:00Z"),
    });
  });

  it("excludes a customer_explicit slot (not a proposal outcome) and a preference_cleared entry", () => {
    const rows = deriveProposalHistory(baseView);
    expect(rows.some((r) => r.slot === "contact_time_preference")).toBe(false);
    expect(rows.some((r) => r.slot === "channel_preference" && r.outcome === "dismissed")).toBe(false);
    expect(rows).toHaveLength(2);
  });

  it("returns an empty list when there are no proposal outcomes", () => {
    expect(deriveProposalHistory({ slots: [], history: [] })).toEqual([]);
  });
});

// 0.0.5 S07 (FR-9): the Write history table's Detail column renders a
// preference_updated row as a readable old->new pair instead of the raw
// details blob every other action falls back to. Tested as a pure function,
// same convention as deriveProposalHistory above.
describe("historyDetail", () => {
  const base: MemoryAuditEntry = {
    entryId: "audit_1",
    at: Date.parse("2026-07-10T09:00:00Z"),
    actorAccountId: "acct_rep_2",
    actorUsername: "rep_2",
    action: "preference_updated",
    slot: "channel_preference",
  };

  it("renders old -> new for a preference_updated row", () => {
    expect(historyDetail({ ...base, oldValue: "sms", newValue: "email" })).toBe('"sms" → "email"');
  });

  // Review finding 5: an empty string is a LEGAL slot value (_require_value only
  // rejects non-strings and >200 chars), so an unquoted pair rendered a dangling
  // " → email" with nothing on the left -- indistinguishable from a bug in the
  // console. Quoting makes "the previous value was empty" readable as such.
  it("renders an empty old value as an explicit empty pair, not a dangling arrow", () => {
    expect(historyDetail({ ...base, oldValue: "", newValue: "email" })).toBe('"" → "email"');
    expect(historyDetail({ ...base, oldValue: "sms", newValue: "" })).toBe('"sms" → ""');
  });

  // Review finding 5: a slot value may itself contain the arrow (or a quote),
  // which unquoted made the pair ambiguous about where old ended and new began.
  it("keeps a value containing the arrow separator unambiguous", () => {
    expect(historyDetail({ ...base, oldValue: "a → b", newValue: "c" })).toBe('"a → b" → "c"');
    expect(historyDetail({ ...base, oldValue: 'say "hi"', newValue: "c" })).toBe(
      '"say \\"hi\\"" → "c"',
    );
  });

  // Review finding 5: the uncovered branch. The existing fallback test below
  // uses preference_cleared, which short-circuits on the action check before
  // ever reaching the old/new presence check -- so a preference_updated row
  // whose details lack the pair (a pre-S07 row, or a partial write) was never
  // exercised. It must fall back to the raw detail, not render "undefined".
  it("falls back to entry.detail for a preference_updated row missing old/new", () => {
    expect(historyDetail({ ...base, detail: '{"slot":"channel_preference"}' })).toBe(
      '{"slot":"channel_preference"}',
    );
    expect(historyDetail({ ...base, oldValue: "sms", detail: "{}" })).toBe("{}");
    expect(historyDetail({ ...base, newValue: "email" })).toBe("");
  });

  it("falls back to entry.detail for any other action", () => {
    expect(
      historyDetail({
        ...base,
        action: "preference_cleared",
        oldValue: undefined,
        newValue: undefined,
        detail: '{"initiator":"rep"}',
      }),
    ).toBe('{"initiator":"rep"}');
  });

  it("falls back to an empty string when neither old/new nor detail is present", () => {
    expect(historyDetail({ ...base, action: "proposal_dismissed" })).toBe("");
  });
});
