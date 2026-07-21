import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  handleClearPreferenceViaApi,
  handleDismissProposalViaApi,
  handleGetPreferencesViaApi,
  handleUpsertPreferenceViaApi,
} from "./preferences";

// The acting account baked into a write client (ADR-0141). Reads pass no actor
// (fail-open); writes must, so the write-path helpers below set this.
const WRITE_ACTOR = "seed-rep";

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  actorAccountId?: string,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    actorAccountId,
    fetchImpl,
  });
}

type SentDispatch = {
  tool: string;
  action: string;
  params: Record<string, unknown>;
  actor_account_id?: string;
};

function jsonReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/cases/x/preferences", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleGetPreferencesViaApi", () => {
  it("returns the mapped preferences and strips binding_key", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return new Response(
        JSON.stringify({
          ok: true,
          data: {
            binding_key: "cust_900",
            preferences: {
              contact_time_preference: "evenings",
              channel_preference: "sms",
              unknown_slot: "should be dropped",
            },
          },
        }),
        { status: 200 },
      );
    });

    const res = await handleGetPreferencesViaApi(client, "case_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      preferences: Record<string, string>;
      binding_key?: string;
    };
    expect(body.preferences).toEqual({
      contact_time_preference: "evenings",
      channel_preference: "sms",
    });
    expect(body.binding_key).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain("cust_900");
    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_customer_memory");
    expect(sent?.action).toBe("get_preferences");
    expect(sent?.params).toEqual({ case_id: "case_1" });
  });

  it("reads with no actor (fail-open)", async () => {
    const res = await handleGetPreferencesViaApi(
      apiClient(
        async () =>
          new Response(JSON.stringify({ ok: true, data: { preferences: {} } }), {
            status: 200,
          }),
      ),
      "case_1",
    );
    expect(res.status).toBe(200);
    expect((await res.json()) as { preferences: unknown }).toEqual({ preferences: {} });
  });

  it("maps a governed denial to its per-class status (ADR-0104)", async () => {
    const res = await handleGetPreferencesViaApi(
      apiClient(
        async () =>
          new Response(
            JSON.stringify({
              ok: false,
              error: { class: "policy_blocked", message: "no" },
            }),
            { status: 200 },
          ),
      ),
      "case_1",
    );
    expect(res.status).toBe(403);
  });
});

describe("handleUpsertPreferenceViaApi", () => {
  function writeClient(capture?: (sent: SentDispatch) => void): HermesApiClient {
    return apiClient(async (_url, init) => {
      const sent = JSON.parse(init.body as string) as SentDispatch;
      capture?.(sent);
      return new Response(
        JSON.stringify({
          ok: true,
          data: {
            binding_key: "cust_900",
            slot: sent.params.key,
            value: sent.params.value,
            source: "workbench_correction",
            evidence: null,
            stored: true,
          },
        }),
        { status: 200 },
      );
    }, WRITE_ACTOR);
  }

  it("dispatches case_id/key/value and returns a confirmation without the binding key", async () => {
    let captured: SentDispatch | null = null;
    const res = await handleUpsertPreferenceViaApi(
      jsonReq({ slot: "contact_time_preference", value: "evenings" }),
      writeClient((s) => (captured = s)),
      "case_1",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      slot: string;
      value: string;
      stored: boolean;
      binding_key?: string;
    };
    expect(body).toEqual({
      slot: "contact_time_preference",
      value: "evenings",
      stored: true,
    });
    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_customer_memory");
    expect(sent?.action).toBe("upsert_preference");
    expect(sent?.params).toEqual({
      case_id: "case_1",
      key: "contact_time_preference",
      value: "evenings",
    });
    // I1 positive parity: the governed write carries the acting account.
    expect(sent?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("400s an invalid slot before any dispatch", async () => {
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
    }, WRITE_ACTOR);
    const res = await handleUpsertPreferenceViaApi(
      jsonReq({ slot: "not_a_real_slot", value: "x" }),
      client,
      "case_1",
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s a missing slot", async () => {
    const res = await handleUpsertPreferenceViaApi(
      jsonReq({ value: "x" }),
      writeClient(),
      "case_1",
    );
    expect(res.status).toBe(400);
  });

  it("400s an empty value", async () => {
    const res = await handleUpsertPreferenceViaApi(
      jsonReq({ slot: "channel_preference", value: "  " }),
      writeClient(),
      "case_1",
    );
    expect(res.status).toBe(400);
  });

  it("maps a governed denial to its per-class status", async () => {
    const res = await handleUpsertPreferenceViaApi(
      jsonReq({ slot: "channel_preference", value: "sms" }),
      apiClient(
        async () =>
          new Response(
            JSON.stringify({
              ok: false,
              error: { class: "policy_blocked", message: "no" },
            }),
            { status: 200 },
          ),
        WRITE_ACTOR,
      ),
      "case_1",
    );
    expect(res.status).toBe(403);
  });
});

describe("handleClearPreferenceViaApi", () => {
  function writeClient(capture?: (sent: SentDispatch) => void): HermesApiClient {
    return apiClient(async (_url, init) => {
      const sent = JSON.parse(init.body as string) as SentDispatch;
      capture?.(sent);
      return new Response(
        JSON.stringify({
          ok: true,
          data: { binding_key: "cust_900", slot: sent.params.key, cleared: true },
        }),
        { status: 200 },
      );
    }, WRITE_ACTOR);
  }

  it("dispatches case_id/key and returns a confirmation without the binding key", async () => {
    let captured: SentDispatch | null = null;
    const res = await handleClearPreferenceViaApi(
      jsonReq({ slot: "delivery_habit_note" }),
      writeClient((s) => (captured = s)),
      "case_1",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slot: string; cleared: boolean; binding_key?: string };
    expect(body).toEqual({ slot: "delivery_habit_note", cleared: true });
    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_customer_memory");
    expect(sent?.action).toBe("clear_preference");
    expect(sent?.params).toEqual({ case_id: "case_1", key: "delivery_habit_note" });
    expect(sent?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("400s an invalid slot before any dispatch", async () => {
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
    }, WRITE_ACTOR);
    const res = await handleClearPreferenceViaApi(jsonReq({ slot: "nope" }), client, "case_1");
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("maps a governed denial to its per-class status", async () => {
    const res = await handleClearPreferenceViaApi(
      jsonReq({ slot: "channel_preference" }),
      apiClient(
        async () =>
          new Response(
            JSON.stringify({ ok: false, error: { class: "vendor_timeout", message: "no" } }),
            { status: 200 },
          ),
        WRITE_ACTOR,
      ),
      "case_1",
    );
    expect(res.status).toBe(504);
  });
});

describe("handleDismissProposalViaApi", () => {
  function writeClient(capture?: (sent: SentDispatch) => void): HermesApiClient {
    return apiClient(async (_url, init) => {
      const sent = JSON.parse(init.body as string) as SentDispatch;
      capture?.(sent);
      return new Response(
        JSON.stringify({
          ok: true,
          data: { binding_key: "cust_900", slot: sent.params.key, dismissed: true },
        }),
        { status: 200 },
      );
    }, WRITE_ACTOR);
  }

  it("dispatches dismiss_proposal (not upsert_preference) and persists no slot", async () => {
    let captured: SentDispatch | null = null;
    const res = await handleDismissProposalViaApi(
      jsonReq({
        slot: "contact_time_preference",
        value: "evenings",
        evidenceTurn: "text me evenings",
      }),
      writeClient((s) => (captured = s)),
      "case_1",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      slot: string;
      dismissed: boolean;
      binding_key?: string;
    };
    expect(body).toEqual({ slot: "contact_time_preference", dismissed: true });
    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_customer_memory");
    expect(sent?.action).toBe("dismiss_proposal");
    expect(sent?.params).toEqual({
      case_id: "case_1",
      key: "contact_time_preference",
      value: "evenings",
      evidence: "text me evenings",
    });
    expect(sent?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("400s an invalid slot before any dispatch", async () => {
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
    }, WRITE_ACTOR);
    const res = await handleDismissProposalViaApi(
      jsonReq({ slot: "not_a_real_slot", value: "x" }),
      client,
      "case_1",
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s a missing value", async () => {
    const res = await handleDismissProposalViaApi(
      jsonReq({ slot: "channel_preference" }),
      writeClient(),
      "case_1",
    );
    expect(res.status).toBe(400);
  });

  it("maps a governed denial to its per-class status", async () => {
    const res = await handleDismissProposalViaApi(
      jsonReq({ slot: "channel_preference", value: "sms" }),
      apiClient(
        async () =>
          new Response(
            JSON.stringify({
              ok: false,
              error: { class: "policy_blocked", message: "no" },
            }),
            { status: 200 },
          ),
        WRITE_ACTOR,
      ),
      "case_1",
    );
    expect(res.status).toBe(403);
  });

  it("rejects with no actor and never dispatches the mutation (BFF defense-in-depth)", async () => {
    const seen: string[] = [];
    const client = apiClient(async (_url, init) => {
      const sent = JSON.parse(init.body as string) as SentDispatch;
      seen.push(sent.action);
      return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
    });
    const res = await handleDismissProposalViaApi(
      jsonReq({ slot: "channel_preference", value: "sms" }),
      client,
      "case_1",
    );
    expect(res.status).toBe(403);
    expect(seen).not.toContain("dismiss_proposal");
  });
});

// I1 (ADR-0141 fail-closed actor): defense-in-depth in the BFF. A governed write
// dispatched through a client with NO actor is denied before it ever calls the
// mutation, mirroring cases.ts's identical guarantee for case writes.
describe("governed preference writes require an actor (BFF defense-in-depth)", () => {
  function actorlessClient(seen: string[]): HermesApiClient {
    return apiClient(async (_url, init) => {
      const sent = JSON.parse(init.body as string) as SentDispatch;
      seen.push(sent.action);
      return new Response(
        JSON.stringify({ ok: true, data: { slot: sent.params.key, stored: true } }),
        { status: 200 },
      );
    });
  }

  it("rejects an upsert and never dispatches the mutation", async () => {
    const seen: string[] = [];
    const res = await handleUpsertPreferenceViaApi(
      jsonReq({ slot: "channel_preference", value: "sms" }),
      actorlessClient(seen),
      "case_1",
    );
    expect(res.status).toBe(403);
    expect(((await res.json()) as { errorClass?: string }).errorClass).toBe("policy_blocked");
    expect(seen).not.toContain("upsert_preference");
  });

  it("rejects a clear and never dispatches the mutation", async () => {
    const seen: string[] = [];
    const res = await handleClearPreferenceViaApi(
      jsonReq({ slot: "channel_preference" }),
      actorlessClient(seen),
      "case_1",
    );
    expect(res.status).toBe(403);
    expect(seen).not.toContain("clear_preference");
  });
});
