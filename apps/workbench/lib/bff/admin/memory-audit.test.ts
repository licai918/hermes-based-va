import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleGetMemoryAuditViaApi } from "./memory-audit";

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    actorAccountId: "seed-supervisor",
    fetchImpl,
  });
}

type SentDispatch = { tool: string; action: string; params: Record<string, unknown> };

function dispatchResponse(data: unknown): Response {
  return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
}

describe("handleGetMemoryAuditViaApi", () => {
  it("dispatches get_memory_audit with case_id and strips binding_key", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse({
        binding_key: "cust_900",
        slots: [],
        audit: [],
      });
    });

    const res = await handleGetMemoryAuditViaApi(client, "case_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slots: unknown[]; history: unknown[]; binding_key?: string };
    expect(body.binding_key).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain("cust_900");
    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_customer_memory");
    expect(sent?.action).toBe("get_memory_audit");
    expect(sent?.params).toEqual({ case_id: "case_1" });
  });

  // Acceptance ①(a): "the history payload carries source/actor/timestamps for
  // UI-, draft-, and merge-written rows" -- one row per write source.
  it("preserves source/actor/timestamps for UI-written, draft-written, and merge-written slots", async () => {
    const client = apiClient(async () =>
      dispatchResponse({
        binding_key: "cust_900",
        slots: [
          {
            slot_name: "contact_time_preference",
            slot_value: "mornings",
            source: "employee_confirmed", // UI-written (a rep correction)
            actor_account_id: "acct_rep_1",
            evidence: null,
            created_at: "2026-07-01T10:00:00Z",
            updated_at: "2026-07-01T10:00:00Z",
          },
          {
            slot_name: "channel_preference",
            slot_value: "sms",
            source: "customer_explicit", // draft/turn-written (the customer said so)
            actor_account_id: null,
            evidence: "text me on sms",
            created_at: "2026-07-02T11:00:00Z",
            updated_at: "2026-07-02T11:00:00Z",
          },
          {
            slot_name: "delivery_habit_note",
            slot_value: "leave at dock",
            source: "merged_provisional", // provisional-to-verified merge write
            actor_account_id: null,
            evidence: null,
            created_at: "2026-07-03T12:00:00Z",
            updated_at: "2026-07-03T12:00:00Z",
          },
        ],
        audit: [],
      }),
    );

    const res = await handleGetMemoryAuditViaApi(client, "case_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      slots: Array<{
        slot: string;
        source: string | null;
        actorAccountId: string | null;
        updatedAt: number;
      }>;
    };
    expect(body.slots).toHaveLength(3);
    const bySlot = Object.fromEntries(body.slots.map((s) => [s.slot, s]));
    expect(bySlot.contact_time_preference).toMatchObject({
      source: "employee_confirmed",
      actorAccountId: "acct_rep_1",
    });
    expect(bySlot.channel_preference).toMatchObject({
      source: "customer_explicit",
      actorAccountId: null,
    });
    expect(bySlot.delivery_habit_note).toMatchObject({
      source: "merged_provisional",
      actorAccountId: null,
    });
    for (const slot of body.slots) {
      expect(typeof slot.updatedAt).toBe("number");
      expect(Number.isNaN(slot.updatedAt)).toBe(false);
    }
  });

  // S16 boundary: proposal_dismissed rows must already surface here, not be
  // filtered out (S16 only adds presentation on top of this read).
  it("surfaces proposal_dismissed and preference_cleared history rows with actor/timestamp", async () => {
    const client = apiClient(async () =>
      dispatchResponse({
        binding_key: "cust_900",
        slots: [],
        audit: [
          {
            id: "audit_1",
            account_id: "acct_rep_1",
            action: "proposal_dismissed",
            target_type: "customer_memory_slot",
            target_id: "channel_preference",
            details: { slot: "channel_preference", value: "sms", evidence: "text me" },
            created_at: "2026-07-01T09:00:00Z",
          },
          {
            id: "audit_2",
            account_id: "acct_sup_1",
            action: "preference_cleared",
            target_type: "customer_memory_slot",
            target_id: "channel_preference",
            details: { slot: "channel_preference", binding_key: "cust_900" },
            created_at: "2026-07-04T09:00:00Z",
          },
        ],
      }),
    );

    const res = await handleGetMemoryAuditViaApi(client, "case_1");
    const body = (await res.json()) as {
      history: Array<{ action: string; actorAccountId: string | null; slot: string | null; at: number }>;
    };
    const actions = body.history.map((h) => h.action);
    expect(actions).toContain("proposal_dismissed");
    expect(actions).toContain("preference_cleared");
    const cleared = body.history.find((h) => h.action === "preference_cleared");
    expect(cleared?.actorAccountId).toBe("acct_sup_1");
    expect(cleared?.slot).toBe("channel_preference");
    expect(typeof cleared?.at).toBe("number");
  });

  it("maps a governed denial to its per-class status (ADR-0104)", async () => {
    const res = await handleGetMemoryAuditViaApi(
      apiClient(
        async () =>
          new Response(
            JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
            { status: 200 },
          ),
      ),
      "case_1",
    );
    expect(res.status).toBe(403);
  });
});
