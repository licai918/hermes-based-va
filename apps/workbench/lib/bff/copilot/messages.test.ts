import { describe, expect, it } from "vitest";
import { WORKBENCH_ROLES } from "@toee/shared";
import type { WorkbenchSession } from "../../auth/session";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleTextlineSendViaApi } from "./messages";

const NOW = 1_700_000_000_000;

function session(accountId = "seed-rep"): WorkbenchSession {
  return {
    accountId,
    username: "rep",
    role: WORKBENCH_ROLES.rep,
    lastActivityAt: NOW,
  };
}

function sendReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/messages/textline/send", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ADR-0141 / #42: governed Textline send over tools:dispatch. Preserves store-path
// 400/404/403 ordering, returns { message }, and writes NO in-memory thread/audit
// (mirror + textline_send audit land server-side).
describe("handleTextlineSendViaApi", () => {
  type FetchLike = (url: string, init: RequestInit) => Promise<Response>;
  type SentDispatch = {
    tool: string;
    action: string;
    params: Record<string, unknown>;
    actor_account_id?: string;
  };

  const WRITE_ACTOR = "seed-rep";
  const eligibleCase = {
    case_id: "case_api",
    channel: "sms",
    status: "in_progress",
    assignee_account_id: WRITE_ACTOR,
    thread_id: "thr_api",
    sms_session_active: true,
    urgent: false,
    identity_summary: "",
    contact_reason: "order_status",
    opened_at: "2026-06-01T12:00:00+00:00",
    last_activity_at: "2026-06-01T13:00:00+00:00",
  };

  function client(
    caseValue: unknown,
    mutationData: unknown,
    capture?: (sent: SentDispatch) => void,
  ): HermesApiClient {
    return new HermesApiClient({
      baseUrl: "http://copilot.internal",
      token: "tok",
      actorAccountId: WRITE_ACTOR,
      fetchImpl: async (_url, init) => {
        const sent = JSON.parse(init.body as string) as SentDispatch;
        capture?.(sent);
        const data =
          sent.action === "get_case" ? { case: caseValue } : mutationData;
        return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
      },
    });
  }

  it("sends on an eligible case and dispatches exactly one governed write", async () => {
    let send: SentDispatch | null = null;
    // Every dispatched action, in order -- a second send_textline_message would
    // still leave `send` above looking fine (it just gets overwritten), so the
    // "exactly one" claim in this test's title is only real once it is checked
    // against the full sequence, not just the last capture (0.0.4 S09 fix wave 1,
    // finding 4 -- messages.test.ts brought up to drafts.test.ts's `seen` array
    // treatment, ADR-0141 / #42).
    const seen: string[] = [];
    const res = await handleTextlineSendViaApi(
      sendReq({ caseId: "case_api", body: "Your tires arrive today." }),
      client(
        eligibleCase,
        {
          message: {
            message_id: "msg_abc",
            conversation_id: "thr_api",
            body: "Your tires arrive today.",
          },
        },
        (sent) => {
          seen.push(sent.action);
          if (sent.action === "send_textline_message") send = sent;
        },
      ),
      session(),
    );
    expect(res.status).toBe(200);
    const payload = (await res.json()) as {
      message: { messageId: string; body: string };
    };
    expect(payload.message.messageId).toBe("msg_abc");
    expect(payload.message.body).toBe("Your tires arrive today.");
    expect(seen).toEqual(["get_case", "send_textline_message"]);
    const dispatched = send as SentDispatch | null;
    expect(dispatched?.tool).toBe("toee_case_manage");
    expect(dispatched?.action).toBe("send_textline_message");
    expect(dispatched?.params).toEqual({
      case_id: "case_api",
      body: "Your tires arrive today.",
    });
    expect(dispatched?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("400s an empty body without network", async () => {
    let called = false;
    const res = await handleTextlineSendViaApi(
      sendReq({ caseId: "case_api", body: "  " }),
      new HermesApiClient({
        baseUrl: "http://copilot.internal",
        token: "tok",
        actorAccountId: WRITE_ACTOR,
        fetchImpl: async () => {
          called = true;
          return new Response("{}", { status: 200 });
        },
      }),
      session(),
    );
    expect(res.status).toBe(400);
    expect(called).toBe(false);
  });

  it("404s an unknown case", async () => {
    const res = await handleTextlineSendViaApi(
      sendReq({ caseId: "missing", body: "hello" }),
      client(null, {}),
      session(),
    );
    expect(res.status).toBe(404);
  });

  it("403s when the case is not eligible (inactive SMS session)", async () => {
    const res = await handleTextlineSendViaApi(
      sendReq({ caseId: "case_api", body: "hello" }),
      client({ ...eligibleCase, sms_session_active: false }, {}),
      session(),
    );
    expect(res.status).toBe(403);
  });

  it("502s on a governed send failure (ADR-0104)", async () => {
    const res = await handleTextlineSendViaApi(
      sendReq({ caseId: "case_api", body: "hello" }),
      new HermesApiClient({
        baseUrl: "http://copilot.internal",
        token: "tok",
        actorAccountId: WRITE_ACTOR,
        fetchImpl: async (_url, init) => {
          const sent = JSON.parse(init.body as string) as SentDispatch;
          if (sent.action === "send_textline_message") {
            return new Response(
              JSON.stringify({
                ok: false,
                error: { class: "unexpected_error", message: "boom" },
              }),
              { status: 200 },
            );
          }
          return new Response(
            JSON.stringify({ ok: true, data: { case: eligibleCase } }),
            { status: 200 },
          );
        },
      }),
      session(),
    );
    expect(res.status).toBe(502);
  });

  // ADR-0083 has THREE preconditions and the store path asserted each separately.
  // Each is re-asserted here on the client seam, including the proof the governed
  // send is never dispatched -- a 403 that still sent the message would be the
  // worst possible regression, and only the dispatch log can catch it.
  function ineligible(caseRow: unknown): {
    client: HermesApiClient;
    seen: string[];
  } {
    const seen: string[] = [];
    return {
      seen,
      client: new HermesApiClient({
        baseUrl: "http://copilot.internal",
        token: "tok",
        actorAccountId: WRITE_ACTOR,
        fetchImpl: async (_url, init) => {
          const sent = JSON.parse(init.body as string) as SentDispatch;
          seen.push(sent.action);
          return new Response(
            JSON.stringify({ ok: true, data: { case: caseRow } }),
            { status: 200 },
          );
        },
      }),
    };
  }

  it("403s an SMS case held by ANOTHER account and never dispatches the send", async () => {
    const { client: c, seen } = ineligible({
      ...eligibleCase,
      assignee_account_id: "seed-other",
    });
    const res = await handleTextlineSendViaApi(
      sendReq({ caseId: "case_api", body: "hello" }),
      c,
      session(),
    );
    expect(res.status).toBe(403);
    expect(seen).not.toContain("send_textline_message");
  });

  it("403s an unclaimed case and never dispatches the send", async () => {
    const { client: c, seen } = ineligible({
      ...eligibleCase,
      assignee_account_id: null,
    });
    const res = await handleTextlineSendViaApi(
      sendReq({ caseId: "case_api", body: "hello" }),
      c,
      session(),
    );
    expect(res.status).toBe(403);
    expect(seen).not.toContain("send_textline_message");
  });

  it("403s a non-SMS case even when the actor holds it", async () => {
    const { client: c, seen } = ineligible({ ...eligibleCase, channel: "email" });
    const res = await handleTextlineSendViaApi(
      sendReq({ caseId: "case_api", body: "hello" }),
      c,
      session(),
    );
    expect(res.status).toBe(403);
    expect(seen).not.toContain("send_textline_message");
  });
});
