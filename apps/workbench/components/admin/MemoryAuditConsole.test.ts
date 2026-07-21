import { describe, expect, it } from "vitest";
import type { MemoryAuditView } from "@/lib/gateway/types";
import { deriveProposalHistory } from "./MemoryAuditConsole";

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
