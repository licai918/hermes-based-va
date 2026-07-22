import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  buildSimulatedInboundEmail,
  buildSimulatedInboundEvent,
  handleGetSimulatorEmailThread,
  handleGetSimulatorThread,
  handleSimulatorEmailIngress,
  handleSimulatorIngress,
  handleSimulatorLinkIdentity,
} from "./simulator";

function jsonReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/simulator/messages", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function emailReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/simulator/email", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("buildSimulatedInboundEvent", () => {
  it("builds the SimpleTexting INCOMING_MESSAGE report shape", () => {
    const event = buildSimulatedInboundEvent({
      fromPhone: "+14165550101",
      body: "Do you have 225/65R17 in stock?",
      eventId: "evt-sim-1",
      nowIso: "2026-07-20T14:00:00.000Z",
    });
    expect(event).toEqual({
      reportId: "rep-evt-sim-1",
      webhookId: "wh-simulator",
      type: "INCOMING_MESSAGE",
      values: {
        messageId: "evt-sim-1",
        text: "Do you have 225/65R17 in stock?",
        accountPhone: "simulator",
        contactPhone: "+14165550101",
        timestamp: "2026-07-20T14:00:00.000Z",
        category: "SMS",
      },
    });
  });

  it("generates an id and ISO timestamp when omitted", () => {
    const event = buildSimulatedInboundEvent({
      fromPhone: "+14165550101",
      body: "hi",
    });
    expect(event.values.messageId).toMatch(/^sim-/);
    const ts = event.values.timestamp;
    expect(() => new Date(ts).toISOString()).not.toThrow();
    expect(new Date(ts).toISOString()).toBe(ts);
  });
});

describe("handleSimulatorIngress", () => {
  it("POSTs the report to the tokened gateway webhook and returns accepted:true", async () => {
    let capturedUrl = "";
    let capturedInit: RequestInit | null = null;
    const res = await handleSimulatorIngress(
      jsonReq({
        fromPhone: "+14165550101",
        body: "Do you have 225/65R17 in stock?",
        conversationId: "conv-sim-1",
      }),
      {
        gatewayUrl: "http://127.0.0.1:8080",
        webhookSecret: "whsec-dev",
        fetchImpl: async (url, init) => {
          capturedUrl = url;
          capturedInit = init;
          return new Response(null, { status: 200 });
        },
      },
    );

    // The token is the auth channel: SimpleTexting signs nothing and its webhook
    // registration accepts no custom header (ADR-0153).
    expect(capturedUrl).toBe(
      "http://127.0.0.1:8080/webhooks/simpletexting?token=whsec-dev",
    );
    const init = capturedInit as unknown as RequestInit;
    expect(init.method).toBe("POST");
    // Exact match, not a per-key check: the token is the whole auth story, so no
    // signature header of any kind may be sent. A re-introduced one fails here.
    const headers = init.headers as Record<string, string>;
    expect(headers).toEqual({ "content-type": "application/json" });
    const sentBody = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(sentBody).toEqual({
      reportId: expect.stringMatching(/^rep-sim-/),
      webhookId: "wh-simulator",
      type: "INCOMING_MESSAGE",
      values: {
        messageId: expect.stringMatching(/^sim-/),
        text: "Do you have 225/65R17 in stock?",
        accountPhone: "simulator",
        contactPhone: "+14165550101",
        timestamp: expect.any(String),
        category: "SMS",
      },
    });

    expect(res.status).toBe(200);
    const payload = (await res.json()) as {
      conversationId: string;
      eventId: string;
      accepted: boolean;
    };
    expect(payload.conversationId).toBe("+14165550101");
    expect(payload.eventId).toMatch(/^sim-/);
    expect(payload.accepted).toBe(true);
  });

  it("reports the contact phone as the conversation id", async () => {
    const res = await handleSimulatorIngress(
      jsonReq({ fromPhone: "+14165550101", body: "hi" }),
      {
        gatewayUrl: "http://127.0.0.1:8080",
        webhookSecret: "whsec-dev",
        fetchImpl: async () => new Response(null, { status: 200 }),
      },
    );
    const payload = (await res.json()) as { conversationId: string };
    expect(payload.conversationId).toBe("+14165550101");
  });

  it("reports accepted:false when the gateway rejects the token (401)", async () => {
    const res = await handleSimulatorIngress(
      jsonReq({ fromPhone: "+14165550101", body: "hi", conversationId: "conv-x" }),
      {
        gatewayUrl: "http://127.0.0.1:8080",
        webhookSecret: "whsec-dev",
        fetchImpl: async () => new Response(null, { status: 401 }),
      },
    );
    expect(res.status).toBe(200);
    const payload = (await res.json()) as { accepted: boolean };
    expect(payload.accepted).toBe(false);
  });

  it("returns a structured 502 problem when the gateway fetch rejects (e.g. ECONNREFUSED)", async () => {
    const res = await handleSimulatorIngress(
      jsonReq({ fromPhone: "+14165550101", body: "hi", conversationId: "conv-x" }),
      {
        gatewayUrl: "http://127.0.0.1:8080",
        webhookSecret: "whsec-dev",
        fetchImpl: async () => {
          throw new TypeError("fetch failed: ECONNREFUSED");
        },
      },
    );
    expect(res.status).toBe(502);
    const payload = (await res.json()) as { error: string };
    expect(payload.error).toBe("service unavailable");
  });

  it("400s a missing fromPhone before any fetch", async () => {
    let dispatched = false;
    const res = await handleSimulatorIngress(jsonReq({ body: "hi" }), {
      gatewayUrl: "http://127.0.0.1:8080",
      webhookSecret: "whsec-dev",
      fetchImpl: async () => {
        dispatched = true;
        return new Response(null, { status: 200 });
      },
    });
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s a missing body before any fetch", async () => {
    let dispatched = false;
    const res = await handleSimulatorIngress(jsonReq({ fromPhone: "+14165550101" }), {
      gatewayUrl: "http://127.0.0.1:8080",
      webhookSecret: "whsec-dev",
      fetchImpl: async () => {
        dispatched = true;
        return new Response(null, { status: 200 });
      },
    });
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });
});

describe("buildSimulatedInboundEmail", () => {
  it("builds the simulated email shape (id/conversation_id/from/subject/body/received_at/type)", () => {
    const event = buildSimulatedInboundEmail({
      fromAddress: "accounts@acme-fleet.example",
      subject: "Order 10444",
      body: "Where is my order?",
      conversationId: "conv-em-1",
      eventId: "evt-em-1",
      nowIso: "2026-07-20T14:00:00.000Z",
    });
    expect(event).toEqual({
      id: "evt-em-1",
      conversation_id: "conv-em-1",
      from: "accounts@acme-fleet.example",
      subject: "Order 10444",
      body: "Where is my order?",
      received_at: "2026-07-20T14:00:00.000Z",
      type: "email.received",
    });
  });
});

describe("handleSimulatorEmailIngress", () => {
  it("POSTs the email event to the tokened simulated-email webhook and returns accepted:true", async () => {
    let capturedUrl = "";
    let capturedInit: RequestInit | null = null;
    const res = await handleSimulatorEmailIngress(
      emailReq({
        from: "accounts@acme-fleet.example",
        subject: "Order 10444",
        body: "Where is my order?",
        conversationId: "conv-em-1",
      }),
      {
        gatewayUrl: "http://127.0.0.1:8080",
        webhookSecret: "whsec-dev",
        fetchImpl: async (url, init) => {
          capturedUrl = url;
          capturedInit = init;
          return new Response(null, { status: 200 });
        },
      },
    );

    expect(capturedUrl).toBe(
      "http://127.0.0.1:8080/webhooks/simulated-email?token=whsec-dev",
    );
    const init = capturedInit as unknown as RequestInit;
    // Same invariant as the SMS ingress above: token only, never a signature header.
    const headers = init.headers as Record<string, string>;
    expect(headers).toEqual({ "content-type": "application/json" });
    const sentBody = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(sentBody).toEqual({
      id: expect.stringMatching(/^sim-/),
      conversation_id: "conv-em-1",
      from: "accounts@acme-fleet.example",
      subject: "Order 10444",
      body: "Where is my order?",
      received_at: expect.any(String),
      type: "email.received",
    });
    expect(res.status).toBe(200);
    const payload = (await res.json()) as { accepted: boolean; conversationId: string };
    expect(payload.accepted).toBe(true);
    expect(payload.conversationId).toBe("conv-em-1");
  });

  it("400s a missing from before any fetch", async () => {
    let dispatched = false;
    const res = await handleSimulatorEmailIngress(
      emailReq({ subject: "hi", body: "hi" }),
      {
        gatewayUrl: "http://127.0.0.1:8080",
        webhookSecret: "whsec-dev",
        fetchImpl: async () => {
          dispatched = true;
          return new Response(null, { status: 200 });
        },
      },
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("allows an empty subject and generates a conversationId", async () => {
    const res = await handleSimulatorEmailIngress(
      emailReq({ from: "a@b.com", body: "hi" }),
      {
        gatewayUrl: "http://127.0.0.1:8080",
        webhookSecret: "whsec-dev",
        fetchImpl: async () => new Response(null, { status: 200 }),
      },
    );
    const payload = (await res.json()) as { conversationId: string };
    // Email keeps its own conversation id — unlike SMS, where the contact phone
    // IS the conversation (SimpleTexting has no conversation resource).
    expect(payload.conversationId).toMatch(/^sim-/);
  });
});

describe("handleSimulatorLinkIdentity", () => {
  function linkReq(body: unknown): Request {
    return new Request("http://localhost/api/copilot/simulator/link-identity", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function apiClient(
    fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  ): HermesApiClient {
    return new HermesApiClient({
      baseUrl: "http://copilot.internal",
      token: "tok",
      actorAccountId: "acct_1",
      fetchImpl,
    });
  }

  type SentDispatch = {
    tool: string;
    action: string;
    params: Record<string, unknown>;
    actor_account_id: string;
  };

  it("dispatches link_identity carrying the correct pair of identities", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return new Response(
        JSON.stringify({
          ok: true,
          data: {
            outcome: "linked",
            channel: "sms",
            channel_identity: "+14165559999",
            shopify_customer_id: "gid://shopify/Customer/1001",
          },
        }),
        { status: 200 },
      );
    });

    const res = await handleSimulatorLinkIdentity(
      linkReq({
        channelIdentity: "+14165559999",
        shopifyCustomerId: "gid://shopify/Customer/1001",
        companyName: "Acme Fleet",
      }),
      client,
    );

    expect(res.status).toBe(200);
    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_identity_lookup");
    expect(sent?.action).toBe("link_identity");
    expect(sent?.params).toEqual({
      channel: "sms",
      channel_identity: "+14165559999",
      shopify_customer_id: "gid://shopify/Customer/1001",
      company_name: "Acme Fleet",
    });
    expect(sent?.actor_account_id).toBe("acct_1");

    const body = (await res.json()) as {
      linked: boolean;
      channel: string;
      channelIdentity: string;
      shopifyCustomerId: string;
    };
    expect(body).toEqual({
      linked: true,
      channel: "sms",
      channelIdentity: "+14165559999",
      shopifyCustomerId: "gid://shopify/Customer/1001",
    });
  });

  it("defaults channel to sms and omits companyName when absent", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
    });

    await handleSimulatorLinkIdentity(
      linkReq({
        channelIdentity: "+14165559999",
        shopifyCustomerId: "gid://shopify/Customer/1001",
      }),
      client,
    );

    const sent = captured as SentDispatch | null;
    expect(sent?.params).toEqual({
      channel: "sms",
      channel_identity: "+14165559999",
      shopify_customer_id: "gid://shopify/Customer/1001",
    });
  });

  it("400s a missing channelIdentity before any dispatch", async () => {
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
    });
    const res = await handleSimulatorLinkIdentity(
      linkReq({ shopifyCustomerId: "gid://shopify/Customer/1001" }),
      client,
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s a missing shopifyCustomerId before any dispatch", async () => {
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
    });
    const res = await handleSimulatorLinkIdentity(
      linkReq({ channelIdentity: "+14165559999" }),
      client,
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("maps a policy_blocked denial (e.g. not simulated mode) to 403", async () => {
    const client = apiClient(
      async () =>
        new Response(
          JSON.stringify({
            ok: false,
            error: { class: "policy_blocked", message: "not simulated" },
          }),
          { status: 200 },
        ),
    );
    const res = await handleSimulatorLinkIdentity(
      linkReq({
        channelIdentity: "+14165559999",
        shopifyCustomerId: "gid://shopify/Customer/1001",
      }),
      client,
    );
    expect(res.status).toBe(403);
  });
});

describe("handleGetSimulatorThread", () => {
  function apiClient(
    fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  ): HermesApiClient {
    return new HermesApiClient({ baseUrl: "http://copilot.internal", token: "tok", fetchImpl });
  }

  it("dispatches get_thread_by_phone and maps the returned messages", async () => {
    type SentDispatch = { tool: string; action: string; params: Record<string, unknown> };
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return new Response(
        JSON.stringify({
          ok: true,
          data: {
            case: { case_id: "case_1" },
            messages: [
              {
                id: "mt_1",
                customer_thread_id: "thr_1",
                author: "customer",
                channel: "sms",
                body: "Do you have 225/65R17?",
                created_at: "2026-07-20T14:00:00.000Z",
                auto_handled: false,
                active_case_segment: true,
              },
              {
                id: "mt_2",
                customer_thread_id: "thr_1",
                author: "hermes",
                channel: "sms",
                body: "Yes, in stock",
                created_at: "2026-07-20T14:00:05.000Z",
                auto_handled: false,
                active_case_segment: true,
              },
            ],
          },
        }),
        { status: 200 },
      );
    });

    const res = await handleGetSimulatorThread(client, "+14165550101");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      caseId: string | null;
      messages: Array<{ body: string | null; author: string }>;
    };
    expect(body.caseId).toBe("case_1");
    expect(body.messages.map((m) => m.body)).toEqual([
      "Do you have 225/65R17?",
      "Yes, in stock",
    ]);
    expect(body.messages.map((m) => m.author)).toEqual(["customer", "hermes"]);
    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_workbench_read");
    expect(sent?.action).toBe("get_thread_by_phone");
    expect(sent?.params).toEqual({ from_phone: "+14165550101" });
  });

  it("returns an empty thread for a phone with no case yet", async () => {
    const client = apiClient(
      async () =>
        new Response(JSON.stringify({ ok: true, data: { case: null, messages: [] } }), {
          status: 200,
        }),
    );
    const res = await handleGetSimulatorThread(client, "+19995550000");
    expect(res.status).toBe(200);
    expect((await res.json()) as { caseId: string | null; messages: unknown[] }).toEqual({
      caseId: null,
      messages: [],
    });
  });

  it("maps a governed denial to its per-class status (ADR-0104)", async () => {
    const client = apiClient(
      async () =>
        new Response(
          JSON.stringify({ ok: false, error: { class: "vendor_timeout", message: "no" } }),
          { status: 200 },
        ),
    );
    const res = await handleGetSimulatorThread(client, "+14165550101");
    expect(res.status).toBe(504);
  });
});

describe("handleGetSimulatorEmailThread", () => {
  function apiClient(
    fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  ): HermesApiClient {
    return new HermesApiClient({ baseUrl: "http://copilot.internal", token: "tok", fetchImpl });
  }

  it("dispatches get_thread_by_email and maps the returned messages", async () => {
    type SentDispatch = { tool: string; action: string; params: Record<string, unknown> };
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return new Response(
        JSON.stringify({
          ok: true,
          data: {
            case: { case_id: "case_email_1" },
            messages: [
              {
                id: "mt_1",
                customer_thread_id: "thr_1",
                author: "customer",
                channel: "email",
                body: "Subject: Order 10444\n\nWhere is my order?",
                created_at: "2026-07-20T14:00:00.000Z",
                auto_handled: false,
                active_case_segment: true,
              },
              {
                id: "mt_2",
                customer_thread_id: "thr_1",
                author: "hermes",
                channel: "email",
                body: "Your order ships tomorrow.",
                created_at: "2026-07-20T14:00:05.000Z",
                auto_handled: false,
                active_case_segment: true,
              },
            ],
          },
        }),
        { status: 200 },
      );
    });

    const res = await handleGetSimulatorEmailThread(client, "accounts@acme-fleet.example");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      caseId: string | null;
      messages: Array<{ body: string | null; author: string }>;
    };
    expect(body.caseId).toBe("case_email_1");
    expect(body.messages.map((m) => m.body)).toEqual([
      "Subject: Order 10444\n\nWhere is my order?",
      "Your order ships tomorrow.",
    ]);
    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_workbench_read");
    expect(sent?.action).toBe("get_thread_by_email");
    expect(sent?.params).toEqual({ from_address: "accounts@acme-fleet.example" });
  });

  it("returns an empty thread for an address with no case yet", async () => {
    const client = apiClient(
      async () =>
        new Response(JSON.stringify({ ok: true, data: { case: null, messages: [] } }), {
          status: 200,
        }),
    );
    const res = await handleGetSimulatorEmailThread(client, "nobody@nowhere.example");
    expect(res.status).toBe(200);
    expect((await res.json()) as { caseId: string | null; messages: unknown[] }).toEqual({
      caseId: null,
      messages: [],
    });
  });

  it("maps a governed denial to its per-class status (ADR-0104)", async () => {
    const client = apiClient(
      async () =>
        new Response(
          JSON.stringify({ ok: false, error: { class: "vendor_timeout", message: "no" } }),
          { status: 200 },
        ),
    );
    const res = await handleGetSimulatorEmailThread(client, "accounts@acme-fleet.example");
    expect(res.status).toBe(504);
  });
});
