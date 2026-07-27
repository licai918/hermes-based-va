import { describe, expect, it } from "vitest";
import { HermesAgentClient } from "../../gateway/hermes-agent-client";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleChatViaApi } from "./chat";

// 0.0.4 S09 deleted the deterministic in-memory `handleChat` stub: chat is only
// ever a real unbound internal_copilot agent turn. The turn itself is driven from
// the dispatch server's `scripted_completions` seam in the runtime suite; here the
// HermesAgentClient is the seam, so the BFF contract (400 / needs_case / 404 /
// draftCard gating / ADR-0104 error mapping) is asserted without a model.


function chatReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

type ChatResponse = {
  state: string;
  reply: string;
  draftCard?: { channel: string; body: string };
};

describe("handleChatViaApi (chat over the agent-turn API)", () => {
  type FetchLike = (url: string, init: RequestInit) => Promise<Response>;
  const CHAT_REPLY =
    "Case case_api is an open SMS order-status case — the customer is waiting on tracking.";

  function clients(fetchImpl: FetchLike): {
    agent: HermesAgentClient;
    client: HermesApiClient;
  } {
    const cfg = {
      baseUrl: "http://copilot.internal",
      token: "tok",
      actorAccountId: "seed-rep",
      fetchImpl,
    };
    return {
      agent: new HermesAgentClient(cfg),
      client: new HermesApiClient(cfg),
    };
  }

  // Routes the get_case pre-read (tools:dispatch) and the chat reply (agent:turn)
  // over one fake fetch. `caseValue` is the get_case payload (null => unknown case;
  // include `channel` for the draftCard gating); `turn` builds the agent:turn body.
  function fakeFetch(
    caseValue: unknown,
    turn: (init: RequestInit) => Response = () =>
      new Response(
        JSON.stringify({ ok: true, data: { reply: CHAT_REPLY, provenance: {} } }),
        { status: 200 },
      ),
  ): FetchLike {
    return async (url, init) => {
      if (url.endsWith("/v1/agent:turn")) return turn(init);
      return new Response(JSON.stringify({ ok: true, data: { case: caseValue } }), {
        status: 200,
      });
    };
  }

  it("400s an empty message without any network call", async () => {
    let called = false;
    const { agent, client } = clients(async () => {
      called = true;
      return new Response("{}", { status: 200 });
    });

    const res = await handleChatViaApi(chatReq({ message: "   " }), agent, client);

    expect(res.status).toBe(400);
    expect(called).toBe(false);
  });

  it("returns needs_case when no case is selected, without any network call", async () => {
    let called = false;
    const { agent, client } = clients(async () => {
      called = true;
      return new Response("{}", { status: 200 });
    });

    const res = await handleChatViaApi(chatReq({ message: "help me" }), agent, client);

    expect(res.status).toBe(200);
    const body = (await res.json()) as ChatResponse;
    expect(body.state).toBe("needs_case");
    expect(body.reply).toMatch(/select/i);
    expect(body.draftCard).toBeUndefined();
    expect(called).toBe(false);
  });

  it("404s an unknown case (null get_case pre-read)", async () => {
    const { agent, client } = clients(fakeFetch(null));

    const res = await handleChatViaApi(
      chatReq({ caseId: "missing", message: "hi" }),
      agent,
      client,
    );

    expect(res.status).toBe(404);
  });

  it("returns a ready reply from the chat turn for a plain message (no draftCard)", async () => {
    let turnBody: Record<string, unknown> | undefined;
    const { agent, client } = clients(
      fakeFetch({ case_id: "case_api", channel: "sms" }, (init) => {
        turnBody = JSON.parse(init.body as string);
        return new Response(
          JSON.stringify({ ok: true, data: { reply: CHAT_REPLY, provenance: {} } }),
          { status: 200 },
        );
      }),
    );

    const res = await handleChatViaApi(
      chatReq({ caseId: "case_api", message: "what's going on here?" }),
      agent,
      client,
    );

    expect(res.status).toBe(200);
    const body = (await res.json()) as ChatResponse;
    expect(body.state).toBe("ready");
    expect(body.reply).toBe(CHAT_REPLY);
    expect(body.draftCard).toBeUndefined();
    // The chat turn rides the agent:turn route as `channel: "chat"`, message as prompt.
    expect(turnBody).toEqual({
      channel: "chat",
      case_id: "case_api",
      prompt: "what's going on here?",
      actor_account_id: "seed-rep",
    });
  });

  it("attaches an SMS draftCard (the reply) when asked to draft on an SMS case", async () => {
    const { agent, client } = clients(fakeFetch({ case_id: "case_api", channel: "sms" }));

    const res = await handleChatViaApi(
      chatReq({ caseId: "case_api", message: "please draft a reply" }),
      agent,
      client,
    );

    expect(res.status).toBe(200);
    const body = (await res.json()) as ChatResponse;
    expect(body.state).toBe("ready");
    expect(body.draftCard?.channel).toBe("sms");
    // The chat reply IS the suggested SMS reply, surfaced into the editable card.
    expect(body.draftCard?.body).toBe(CHAT_REPLY);
  });

  it("does not attach a draftCard on a non-SMS case", async () => {
    const { agent, client } = clients(
      fakeFetch({ case_id: "case_api", channel: "email" }),
    );

    const res = await handleChatViaApi(
      chatReq({ caseId: "case_api", message: "draft an sms please" }),
      agent,
      client,
    );

    const body = (await res.json()) as ChatResponse;
    expect(body.state).toBe("ready");
    expect(body.draftCard).toBeUndefined();
  });

  it("does not attach a draftCard when the message is not a draft request", async () => {
    const { agent, client } = clients(fakeFetch({ case_id: "case_api", channel: "sms" }));

    const res = await handleChatViaApi(
      chatReq({ caseId: "case_api", message: "what's the customer's name?" }),
      agent,
      client,
    );

    const body = (await res.json()) as ChatResponse;
    expect(body.state).toBe("ready");
    expect(body.draftCard).toBeUndefined();
  });

  it("maps a governed agent-turn failure through ADR-0104 (policy_blocked -> 403)", async () => {
    const { agent, client } = clients(
      fakeFetch({ case_id: "case_api", channel: "sms" }, () =>
        new Response(
          JSON.stringify({
            ok: false,
            error: { class: "policy_blocked", message: "no" },
          }),
          { status: 200 },
        ),
      ),
    );

    const res = await handleChatViaApi(
      chatReq({ caseId: "case_api", message: "hi" }),
      agent,
      client,
    );

    expect(res.status).toBe(403);
  });
});
