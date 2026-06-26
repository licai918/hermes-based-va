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
import { HermesAgentClient } from "../../gateway/hermes-agent-client";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import type { AuditAction } from "../../gateway/types";
import type { CopilotDeps } from "./deps";
import { handleDraft, handleDraftViaApi } from "./drafts";

const NOW = 1_700_000_000_000;

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

function draftReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/drafts/sms", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function actions(caseId: string): AuditAction[] {
  return store.getCaseAuditLog(caseId).map((e) => e.action);
}

describe("handleDraft", () => {
  it("drafts an SMS and writes a draft_generated audit", async () => {
    const res = await handleDraft(
      draftReq({ caseId: "case_ar_urgent", prompt: "reassure them" }),
      deps(),
      "draft_sms",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { draft: { channel: string; draft: string } };
    expect(body.draft.channel).toBe("sms");
    expect(typeof body.draft.draft).toBe("string");
    const entry = store
      .getCaseAuditLog("case_ar_urgent")
      .find((e) => e.action === "draft_generated");
    expect(entry?.detail).toBe("draft_sms");
  });

  it("drafts an email with the draft_email detail", async () => {
    const res = await handleDraft(
      draftReq({ caseId: "case_billing_email" }),
      deps(),
      "draft_email",
    );
    expect(res.status).toBe(200);
    const entry = store
      .getCaseAuditLog("case_billing_email")
      .find((e) => e.action === "draft_generated" && e.detail === "draft_email");
    expect(entry).toBeDefined();
  });

  it("drafts an internal note with the draft_internal_note detail", async () => {
    const res = await handleDraft(
      draftReq({ caseId: "case_ar_urgent" }),
      deps(),
      "draft_internal_note",
    );
    expect(res.status).toBe(200);
    expect(actions("case_ar_urgent")).toContain("draft_generated");
  });

  it("400s a missing caseId", async () => {
    const res = await handleDraft(draftReq({ prompt: "hi" }), deps(), "draft_sms");
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const res = await handleDraft(draftReq({ caseId: "nope" }), deps(), "draft_sms");
    expect(res.status).toBe(404);
  });

  it("502s on tool failure without writing an audit", async () => {
    const res = await handleDraft(
      draftReq({ caseId: "case_ar_urgent" }),
      deps({ driver: createMockDriver({}) }),
      "draft_sms",
    );
    expect(res.status).toBe(502);
    expect(actions("case_ar_urgent")).not.toContain("draft_generated");
  });
});

// ADR-0147 Slice 1–2: the draft generated over the per-profile agent-turn API
// (the LLM seam) instead of the in-process mock, env-gated. It MUST preserve the
// store path's surface byte-for-byte per channel: 400/404 caseId validation, the
// channel-shaped `{ draft: ... }` body (sms `{channel,draft}`, email
// `{channel,subject,draft}`, note `{kind,draft}`), and the ADR-0104 error->HTTP
// mapping (governed failure -> 502). The `draft_generated` audit is recorded
// SERVER-SIDE by the agent:turn endpoint now (#47, option i), so this path writes
// NO in-memory audit — the proof of the row moves to a Python datastore test
// (`test_agent_turn_audit`); here we prove the BFF no longer double-writes it.
describe("handleDraftViaApi (drafts over the agent-turn API)", () => {
  type FetchLike = (url: string, init: RequestInit) => Promise<Response>;
  const SMS_DRAFT = {
    channel: "sms",
    draft: "Hi! We're on your order now - tracking to follow.",
    // Provenance rides the API envelope but must NOT leak into the BFF body.
    provenance: { model: "scripted", profile: "internal_copilot" },
  };

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

  // Routes the get_case pre-read (tools:dispatch) and the draft (agent:turn) over
  // one fake fetch. `caseValue` is the get_case payload (null => unknown case);
  // `turn` builds the agent:turn Response (default: the scripted SMS draft).
  function fakeFetch(
    caseValue: unknown,
    turn: (init: RequestInit) => Response = () =>
      new Response(JSON.stringify({ ok: true, data: SMS_DRAFT }), { status: 200 }),
  ): FetchLike {
    return async (url, init) => {
      if (url.endsWith("/v1/agent:turn")) return turn(init);
      return new Response(JSON.stringify({ ok: true, data: { case: caseValue } }), {
        status: 200,
      });
    };
  }

  it("drafts an SMS, returns { draft: { channel, draft } } and writes NO in-memory audit (recorded server-side, #47)", async () => {
    let turnBody: Record<string, unknown> | undefined;
    const { agent, client } = clients(
      fakeFetch({ case_id: "case_api" }, (init) => {
        turnBody = JSON.parse(init.body as string);
        return new Response(JSON.stringify({ ok: true, data: SMS_DRAFT }), {
          status: 200,
        });
      }),
    );

    const res = await handleDraftViaApi(
      draftReq({ caseId: "case_api", prompt: "reassure them" }),
      agent,
      client,
      "draft_sms",
    );

    expect(res.status).toBe(200);
    // Byte-for-byte parity with the store path: { channel, draft }, no provenance.
    expect(await res.json()).toEqual({
      draft: { channel: "sms", draft: SMS_DRAFT.draft },
    });
    // De-dup (#47, option i): the endpoint records draft_generated server-side, so
    // the BFF must NOT also write its in-memory audit on the API path.
    expect(actions("case_api")).not.toContain("draft_generated");
    // The agent-turn body carries the channel, case, prompt + acting account.
    expect(turnBody).toEqual({
      channel: "sms",
      case_id: "case_api",
      prompt: "reassure them",
      actor_account_id: "seed-rep",
    });
  });

  it("400s a missing caseId without any network call", async () => {
    let called = false;
    const { agent, client } = clients(async () => {
      called = true;
      return new Response("{}", { status: 200 });
    });

    const res = await handleDraftViaApi(
      draftReq({ prompt: "hi" }),
      agent,
      client,
      "draft_sms",
    );

    expect(res.status).toBe(400);
    expect(called).toBe(false);
  });

  it("404s an unknown case (null get_case pre-read) without writing an audit", async () => {
    const { agent, client } = clients(fakeFetch(null));

    const res = await handleDraftViaApi(
      draftReq({ caseId: "missing" }),
      agent,
      client,
      "draft_sms",
    );

    expect(res.status).toBe(404);
    expect(actions("missing")).not.toContain("draft_generated");
  });

  it("502s on an agent-turn governed failure without writing an audit (ADR-0104)", async () => {
    const { agent, client } = clients(
      fakeFetch({ case_id: "case_api" }, () =>
        new Response(
          JSON.stringify({
            ok: false,
            error: { class: "unexpected_error", message: "boom" },
          }),
          { status: 200 },
        ),
      ),
    );

    const res = await handleDraftViaApi(
      draftReq({ caseId: "case_api" }),
      agent,
      client,
      "draft_sms",
    );

    expect(res.status).toBe(502);
    expect(actions("case_api")).not.toContain("draft_generated");
  });

  it("maps a governed policy_blocked to 403 (ADR-0104 per-class status)", async () => {
    const { agent, client } = clients(
      fakeFetch({ case_id: "case_api" }, () =>
        new Response(
          JSON.stringify({
            ok: false,
            error: { class: "policy_blocked", message: "no" },
          }),
          { status: 200 },
        ),
      ),
    );

    const res = await handleDraftViaApi(
      draftReq({ caseId: "case_api" }),
      agent,
      client,
      "draft_sms",
    );

    expect(res.status).toBe(403);
  });

  // Slice 2: email + note channels. Each must replicate the in-process tool output
  // shape byte-for-byte (email keys on channel + subject, note keys on kind), with
  // provenance stripped, and audit `draft_generated` with the per-channel detail.
  const EMAIL_DRAFT = {
    channel: "email",
    subject: "Re: your Toee Tire case case_api",
    draft: "Hi there,\n\nWe're looking into your order now.\n\nRegards, Toee Tire",
    provenance: { model: "scripted", profile: "internal_copilot" },
  };
  const NOTE_DRAFT = {
    kind: "internal_note",
    draft: "Customer wants a refund; order verified — suggest issuing a credit.",
    provenance: { model: "scripted", profile: "internal_copilot" },
  };

  it("drafts an email and returns { draft: { channel, subject, draft } } (no provenance)", async () => {
    const { agent, client } = clients(
      fakeFetch({ case_id: "case_api" }, () =>
        new Response(JSON.stringify({ ok: true, data: EMAIL_DRAFT }), { status: 200 }),
      ),
    );

    const res = await handleDraftViaApi(
      draftReq({ caseId: "case_api" }),
      agent,
      client,
      "draft_email",
    );

    expect(res.status).toBe(200);
    // Byte-for-byte parity with the in-process email shape; provenance stripped.
    expect(await res.json()).toEqual({
      draft: {
        channel: "email",
        subject: EMAIL_DRAFT.subject,
        draft: EMAIL_DRAFT.draft,
      },
    });
    // De-dup (#47): the email draft audit is recorded server-side, not in-memory.
    expect(actions("case_api")).not.toContain("draft_generated");
  });

  it("drafts an internal note and returns { draft: { kind, draft } } (no channel, no provenance)", async () => {
    const { agent, client } = clients(
      fakeFetch({ case_id: "case_api" }, () =>
        new Response(JSON.stringify({ ok: true, data: NOTE_DRAFT }), { status: 200 }),
      ),
    );

    const res = await handleDraftViaApi(
      draftReq({ caseId: "case_api" }),
      agent,
      client,
      "draft_internal_note",
    );

    expect(res.status).toBe(200);
    // Note keys on `kind`, never `channel`; provenance stripped.
    expect(await res.json()).toEqual({
      draft: { kind: "internal_note", draft: NOTE_DRAFT.draft },
    });
    // De-dup (#47): the note draft audit is recorded server-side, not in-memory.
    expect(actions("case_api")).not.toContain("draft_generated");
  });

  it("404s an unknown case for email without writing an audit", async () => {
    const { agent, client } = clients(fakeFetch(null));

    const res = await handleDraftViaApi(
      draftReq({ caseId: "missing" }),
      agent,
      client,
      "draft_email",
    );

    expect(res.status).toBe(404);
    expect(actions("missing")).not.toContain("draft_generated");
  });

  it("threads the email channel + case to the agent-turn body", async () => {
    let turnBody: Record<string, unknown> | undefined;
    const { agent, client } = clients(
      fakeFetch({ case_id: "case_api" }, (init) => {
        turnBody = JSON.parse(init.body as string);
        return new Response(JSON.stringify({ ok: true, data: EMAIL_DRAFT }), {
          status: 200,
        });
      }),
    );

    await handleDraftViaApi(
      draftReq({ caseId: "case_api" }),
      agent,
      client,
      "draft_email",
    );

    expect(turnBody).toEqual({
      channel: "email",
      case_id: "case_api",
      actor_account_id: "seed-rep",
    });
  });
});
