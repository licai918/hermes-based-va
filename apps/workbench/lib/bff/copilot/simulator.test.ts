import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  buildSimulatedInboundEvent,
  handleGetSimulatorThread,
  handleSimulatorIngress,
  signLegacyTextlinePayload,
} from "./simulator";

function jsonReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/simulator/messages", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("signLegacyTextlinePayload", () => {
  it("matches a known HMAC-SHA256 hex vector (verify.py's legacy branch)", () => {
    // Independently computed: node -e "crypto.createHmac('sha256',
    // 'test-secret-123').update(<body>, 'utf8').digest('hex')" -- same
    // algorithm as hermes/toee_hermes/gateway/verify.py's non-TGP branch and
    // scripts/simulate-textline-webhook.ps1.
    const body =
      '{"id":"evt_1","conversation_id":"conv_1","from":"+15550001111",' +
      '"body":"hello","received_at":"2026-07-20T14:00:00.000Z","type":"message.created"}';
    const signature = signLegacyTextlinePayload(body, "test-secret-123");
    expect(signature).toBe(
      "8497964c981a1c26f15b8fd7908aeee89dcdab8306d748310956259ba886b1af",
    );
  });

  it("changes when the body changes (not a constant stub)", () => {
    const a = signLegacyTextlinePayload("body-a", "secret");
    const b = signLegacyTextlinePayload("body-b", "secret");
    expect(a).not.toBe(b);
  });
});

describe("buildSimulatedInboundEvent", () => {
  it("builds the legacy flat-JSON shape (id/conversation_id/from/body/received_at/type)", () => {
    const event = buildSimulatedInboundEvent({
      fromPhone: "+14165550101",
      body: "Do you have 225/65R17 in stock?",
      conversationId: "conv-sim-1",
      eventId: "evt-sim-1",
      nowIso: "2026-07-20T14:00:00.000Z",
    });
    expect(event).toEqual({
      id: "evt-sim-1",
      conversation_id: "conv-sim-1",
      from: "+14165550101",
      body: "Do you have 225/65R17 in stock?",
      received_at: "2026-07-20T14:00:00.000Z",
      type: "message.created",
    });
  });

  it("generates an id and ISO timestamp when omitted", () => {
    const event = buildSimulatedInboundEvent({
      fromPhone: "+14165550101",
      body: "hi",
      conversationId: "conv-sim-2",
    });
    expect(event.id).toMatch(/^sim-/);
    expect(() => new Date(event.received_at).toISOString()).not.toThrow();
    expect(new Date(event.received_at).toISOString()).toBe(event.received_at);
  });
});

describe("handleSimulatorIngress", () => {
  it("POSTs the signed flat-JSON event to the gateway webhook and returns accepted:true", async () => {
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

    expect(capturedUrl).toBe("http://127.0.0.1:8080/webhooks/textline");
    const init = capturedInit as unknown as RequestInit;
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers["content-type"]).toBe("application/json");
    const sentBody = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(sentBody).toEqual({
      id: expect.stringMatching(/^sim-/),
      conversation_id: "conv-sim-1",
      from: "+14165550101",
      body: "Do you have 225/65R17 in stock?",
      received_at: expect.any(String),
      type: "message.created",
    });
    // The signature must be the legacy HMAC over the exact bytes sent.
    expect(headers["X-Textline-Signature"]).toBe(
      signLegacyTextlinePayload(init.body as string, "whsec-dev"),
    );

    expect(res.status).toBe(200);
    const payload = (await res.json()) as {
      conversationId: string;
      eventId: string;
      accepted: boolean;
    };
    expect(payload.conversationId).toBe("conv-sim-1");
    expect(payload.eventId).toMatch(/^sim-/);
    expect(payload.accepted).toBe(true);
  });

  it("generates a conversationId when none is supplied", async () => {
    const res = await handleSimulatorIngress(
      jsonReq({ fromPhone: "+14165550101", body: "hi" }),
      {
        gatewayUrl: "http://127.0.0.1:8080",
        webhookSecret: "whsec-dev",
        fetchImpl: async () => new Response(null, { status: 200 }),
      },
    );
    const payload = (await res.json()) as { conversationId: string };
    expect(payload.conversationId).toMatch(/^sim-/);
  });

  it("reports accepted:false when the gateway rejects the signature (401)", async () => {
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
    const body = (await res.json()) as { messages: Array<{ body: string | null; author: string }> };
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
    expect((await res.json()) as { messages: unknown[] }).toEqual({ messages: [] });
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
