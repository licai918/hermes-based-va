import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  handleEraseCustomerMemoryViaApi,
  handleGetMemoryAuditViaApi,
} from "./memory-audit";

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
            actor_username: "rep_1",
            action: "proposal_dismissed",
            target_type: "customer_memory_slot",
            target_id: "channel_preference",
            details: { slot: "channel_preference", value: "sms", evidence: "text me" },
            created_at: "2026-07-01T09:00:00Z",
          },
          {
            id: "audit_2",
            account_id: "acct_sup_1",
            actor_username: "sup_1",
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
      history: Array<{
        action: string;
        actorAccountId: string | null;
        actorUsername?: string | null;
        slot: string | null;
        at: number;
      }>;
    };
    const actions = body.history.map((h) => h.action);
    expect(actions).toContain("proposal_dismissed");
    expect(actions).toContain("preference_cleared");
    const cleared = body.history.find((h) => h.action === "preference_cleared");
    expect(cleared?.actorAccountId).toBe("acct_sup_1");
    expect(cleared?.actorUsername).toBe("sup_1");
    expect(cleared?.slot).toBe("channel_preference");
    expect(typeof cleared?.at).toBe("number");
  });

  // S16 (FR-17): the proposal-history section derives accepted proposals from
  // employee_confirmed slots and dismissed proposals from proposal_dismissed
  // history rows -- both must survive the same handleGetMemoryAuditViaApi
  // response, with the dismissed row's proposed value included (details.value)
  // so the section can show what was proposed, not just that it was dismissed.
  it("carries an accepted slot and a dismissed proposal's value in the same payload", async () => {
    const client = apiClient(async () =>
      dispatchResponse({
        binding_key: "cust_900",
        slots: [
          {
            slot_name: "channel_preference",
            slot_value: "sms",
            source: "employee_confirmed",
            actor_account_id: "acct_rep_4",
            evidence: null,
            created_at: "2026-07-05T09:00:00Z",
            updated_at: "2026-07-05T09:00:00Z",
          },
        ],
        audit: [
          {
            id: "audit_3",
            account_id: "acct_rep_4",
            actor_username: "rep_4",
            action: "proposal_dismissed",
            target_type: "customer_memory_slot",
            target_id: "delivery_habit_note",
            details: { slot: "delivery_habit_note", value: "back door", evidence: "leave it out back" },
            created_at: "2026-07-05T09:05:00Z",
          },
        ],
      }),
    );

    const res = await handleGetMemoryAuditViaApi(client, "case_1");
    const body = (await res.json()) as {
      slots: Array<{ slot: string; value: string; source: string | null; actorAccountId: string | null }>;
      history: Array<{ action: string; slot: string | null; value?: string; actorUsername?: string | null; at: number }>;
    };

    const accepted = body.slots.find((s) => s.source === "employee_confirmed");
    expect(accepted).toMatchObject({ slot: "channel_preference", value: "sms", actorAccountId: "acct_rep_4" });

    const dismissed = body.history.find((h) => h.action === "proposal_dismissed");
    expect(dismissed).toMatchObject({
      slot: "delivery_habit_note",
      value: "back door",
      actorUsername: "rep_4",
    });
    expect(typeof dismissed?.at).toBe("number");
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

// --- 0.0.5 S11 (FR-13, US7): the whole-binding erase --------------------------

describe("handleEraseCustomerMemoryViaApi", () => {
  it("dispatches erase_customer_memory with case_id, attributed to the actor", async () => {
    let captured: SentDispatch | null = null;
    let sentActor: string | undefined;
    const client = apiClient(async (_url, init) => {
      const body = JSON.parse(init.body as string) as SentDispatch & {
        actor_account_id?: string;
      };
      captured = body;
      sentActor = body.actor_account_id;
      return dispatchResponse({
        binding_key: "cust_900",
        bindings: [
          { binding_key: "cust_900", cleared_slots: ["channel_preference"], extra_rows_removed: 0 },
          { binding_key: "provisional:sms:+14165550101", cleared_slots: [], extra_rows_removed: 0 },
        ],
        cleared: 1,
        erased: true,
      });
    });

    const res = await handleEraseCustomerMemoryViaApi(client, "case_1");

    expect(res.status).toBe(200);
    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_customer_memory");
    expect(sent?.action).toBe("erase_customer_memory");
    expect(sent?.params).toEqual({ case_id: "case_1" });
    expect(sentActor).toBe("seed-supervisor");
  });

  it("refuses an actorless client before the network call, not after", async () => {
    // The assertion above does NOT prove dispatchWrite: `dispatch` attaches
    // actor_account_id too whenever the client has one, so swapping the two is
    // invisible to it (found by breaking the handler and watching it stay
    // green). THIS is what dispatchWrite buys -- a governed write with no
    // acting account is refused before it can reach the server (ADR-0141), so
    // the most destructive action in the system cannot be issued unattributed
    // even if the dispatch server's own fail-closed gate were ever weakened.
    let calls = 0;
    const actorless = new HermesApiClient({
      baseUrl: "http://copilot.internal",
      token: "tok",
      fetchImpl: async () => {
        calls += 1;
        return dispatchResponse({ cleared: 4, bindings: [], erased: true });
      },
    });

    const res = await handleEraseCustomerMemoryViaApi(actorless, "case_1");

    expect(res.status).toBe(403);
    expect(calls).toBe(0);
  });

  it("returns counts and never the binding keys the dispatch named", async () => {
    // Every key the erase touched is the customer's raw identity -- the Shopify
    // id AND, since D10, each linked channel's phone/email. None may reach the
    // browser (the copilot preferences handlers' standing rule).
    const client = apiClient(async () =>
      dispatchResponse({
        binding_key: "cust_900",
        bindings: [
          { binding_key: "cust_900", cleared_slots: ["a", "b"], extra_rows_removed: 0 },
          {
            binding_key: "provisional:sms:+14165550101",
            cleared_slots: ["c"],
            extra_rows_removed: 0,
          },
        ],
        cleared: 3,
        erased: true,
      }),
    );

    const res = await handleEraseCustomerMemoryViaApi(client, "case_1");
    const body = (await res.json()) as {
      erased: boolean;
      clearedSlots: number;
      bindingsCleared: number;
    };

    expect(body).toEqual({ erased: true, clearedSlots: 3, bindingsCleared: 2 });
    const raw = JSON.stringify(body);
    expect(raw).not.toContain("cust_900");
    expect(raw).not.toContain("+14165550101");
  });

  it("maps the fail-closed refusal to 403 rather than reporting success", async () => {
    // The action is policy_blocked without an attributed administrator. A
    // handler that swallowed that into a 200 would tell the supervisor the
    // customer's memory was erased when nothing was deleted.
    const res = await handleEraseCustomerMemoryViaApi(
      apiClient(
        async () =>
          new Response(
            JSON.stringify({
              ok: false,
              error: { class: "policy_blocked", message: "no actor" },
            }),
            { status: 200 },
          ),
      ),
      "case_1",
    );
    expect(res.status).toBe(403);
  });
});
