import { beforeEach, describe, expect, it } from "vitest";
import {
  createDefaultMockDriver,
  createMockDriver,
  type ToolDriver,
} from "@toee/domain-adapters";
import { WORKBENCH_ROLES } from "@toee/shared";
import type { WorkbenchSession } from "../../auth/session";
import { createInMemoryGatewayStore, type GatewayStore } from "../../gateway/store";
import { createSeed } from "../../gateway/seed";
import type { AuditAction } from "../../gateway/types";
import type { CopilotDeps } from "./deps";
import { handleTextlineSend, handleTextlineSendViaApi } from "./messages";
import { HermesApiClient } from "../../gateway/hermes-api-client";

// After the seed's anchored timestamps (June 2026) so an appended reply sorts
// last in the thread, matching real wall-clock sends.
const NOW = 1_800_000_000_000;

let store: GatewayStore;
let driver: ToolDriver;

beforeEach(() => {
  store = createInMemoryGatewayStore(createSeed());
  driver = createDefaultMockDriver();
});

function session(): WorkbenchSession {
  return {
    accountId: "seed-rep",
    username: "rep",
    role: WORKBENCH_ROLES.rep,
    lastActivityAt: NOW,
  };
}

function deps(override?: Partial<CopilotDeps>): CopilotDeps {
  return { store, driver, session: session(), now: NOW, ...override };
}

function sendReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/messages/textline/send", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function actions(caseId: string): AuditAction[] {
  return store.getCaseAuditLog(caseId).map((e) => e.action);
}

describe("handleTextlineSend", () => {
  it("sends on an eligible (claimed, active SMS) case: appends thread + audit", async () => {
    store.claimCase("case_ar_urgent", "seed-rep");
    const before = store.getThread("case_ar_urgent").length;

    const res = await handleTextlineSend(
      sendReq({ caseId: "case_ar_urgent", body: "Your tires arrive today." }),
      deps(),
    );
    expect(res.status).toBe(200);
    const payload = (await res.json()) as { message: { messageId: string } };
    expect(payload.message.messageId).toBeTruthy();

    const thread = store.getThread("case_ar_urgent");
    expect(thread.length).toBe(before + 1);
    const last = thread[thread.length - 1]!;
    expect(last.author).toBe("workbench");
    expect(last.body).toBe("Your tires arrive today.");
    expect(actions("case_ar_urgent")).toContain("textline_send");
  });

  it("400s an empty body before any case lookup", async () => {
    const res = await handleTextlineSend(
      sendReq({ caseId: "case_ar_urgent", body: "  " }),
      deps(),
    );
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const res = await handleTextlineSend(
      sendReq({ caseId: "nope", body: "hello" }),
      deps(),
    );
    expect(res.status).toBe(404);
  });

  it("403s when the case is not claimed by the acting account", async () => {
    const res = await handleTextlineSend(
      sendReq({ caseId: "case_ar_urgent", body: "hello" }),
      deps(),
    );
    expect(res.status).toBe(403);
  });

  it("403s a non-SMS case even when assigned to the actor", async () => {
    const res = await handleTextlineSend(
      sendReq({ caseId: "case_billing_email", body: "hello" }),
      deps(),
    );
    expect(res.status).toBe(403);
  });

  it("403s an SMS case with no active SMS session", async () => {
    // case_resolved is sms + assigned seed-rep but smsSessionActive is false.
    const res = await handleTextlineSend(
      sendReq({ caseId: "case_resolved", body: "hello" }),
      deps(),
    );
    expect(res.status).toBe(403);
  });

  it("502s on tool failure without fabricating a thread message or audit", async () => {
    store.claimCase("case_ar_urgent", "seed-rep");
    const before = store.getThread("case_ar_urgent").length;

    const res = await handleTextlineSend(
      sendReq({ caseId: "case_ar_urgent", body: "hello" }),
      deps({ driver: createMockDriver({}) }),
    );
    expect(res.status).toBe(502);
    expect(store.getThread("case_ar_urgent").length).toBe(before);
    expect(actions("case_ar_urgent")).not.toContain("textline_send");
  });
});

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

  it("sends on an eligible case and writes NO in-memory thread or audit", async () => {
    let send: SentDispatch | null = null;
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
          if (sent.action === "send_textline_message") send = sent;
        },
      ),
      deps(),
    );
    expect(res.status).toBe(200);
    const payload = (await res.json()) as {
      message: { messageId: string; body: string };
    };
    expect(payload.message.messageId).toBe("msg_abc");
    expect(payload.message.body).toBe("Your tires arrive today.");
    expect(actions("case_api")).not.toContain("textline_send");
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
      deps(),
    );
    expect(res.status).toBe(400);
    expect(called).toBe(false);
  });

  it("404s an unknown case", async () => {
    const res = await handleTextlineSendViaApi(
      sendReq({ caseId: "missing", body: "hello" }),
      client(null, {}),
      deps(),
    );
    expect(res.status).toBe(404);
  });

  it("403s when the case is not eligible (inactive SMS session)", async () => {
    const res = await handleTextlineSendViaApi(
      sendReq({ caseId: "case_api", body: "hello" }),
      client({ ...eligibleCase, sms_session_active: false }, {}),
      deps(),
    );
    expect(res.status).toBe(403);
  });

  it("502s on a governed send failure without in-memory audit", async () => {
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
      deps(),
    );
    expect(res.status).toBe(502);
    expect(actions("case_api")).not.toContain("textline_send");
  });
});
