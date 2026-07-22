import { beforeEach, describe, expect, it } from "vitest";
import { WORKBENCH_ROLES } from "@toee/shared";
import { createInMemoryAccountStore } from "../../auth/account-store";
import type { WorkbenchSession } from "../../auth/session";
import { createInMemoryEvalStore } from "../../gateway/eval-store";
import {
  createInMemoryKnowledgeStore,
  type KnowledgeStore,
  type PolicySlot,
} from "../../gateway/knowledge-store";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import type { AdminDeps } from "./deps";
import {
  handleGetCorpusStatusViaApi,
  handleListSlots,
  handleListSlotsViaApi,
  handleProbeQueryViaApi,
  handleTriggerReingestViaApi,
  handleRollbackSlot,
  handleRollbackSlotViaApi,
  handleSaveDraft,
  handleSaveDraftViaApi,
  handleSubmitSlot,
  handleSubmitSlotViaApi,
} from "./knowledge";

const NOW = 1_700_000_000_000;

// Eval + account stores are never read or mutated by the knowledge handlers, so
// build them once (the account store seeds via scrypt, which is slow).
const evalStore = createInMemoryEvalStore([]);
const accounts = createInMemoryAccountStore(0);

let knowledge: KnowledgeStore;

beforeEach(() => {
  knowledge = createInMemoryKnowledgeStore();
});

const session: WorkbenchSession = {
  accountId: "seed-supervisor",
  username: "supervisor",
  role: WORKBENCH_ROLES.supervisor,
  lastActivityAt: NOW,
};

function deps(): AdminDeps {
  return { knowledge, evalStore, accounts, session, now: NOW };
}

function putReq(body: unknown): Request {
  return new Request("http://localhost/api/admin/knowledge/slots/x", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleListSlots", () => {
  it("returns every required policy slot", async () => {
    const res = handleListSlots(deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slots: PolicySlot[] };
    expect(body.slots).toHaveLength(6);
    expect(body.slots.map((s) => s.slotId)).toContain("business-hours");
  });
});

describe("handleSaveDraft", () => {
  it("saves draft text and flips an empty slot to draft", async () => {
    const res = await handleSaveDraft(
      putReq({ draftText: "Returns accepted within 30 days." }),
      "returns-exchanges",
      deps(),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slot: PolicySlot };
    expect(body.slot.draftText).toBe("Returns accepted within 30 days.");
    expect(body.slot.status).toBe("draft");
  });

  it("404s an unknown slot", async () => {
    const res = await handleSaveDraft(
      putReq({ draftText: "anything" }),
      "ghost-slot",
      deps(),
    );
    expect(res.status).toBe(404);
  });
});

describe("handleSubmitSlot", () => {
  it("submits a draft slot for eval", async () => {
    const res = handleSubmitSlot("order-delivery", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slot: PolicySlot };
    expect(body.slot.status).toBe("pending_eval");
  });

  it("409s when the slot has no draft", async () => {
    const res = handleSubmitSlot("returns-exchanges", deps());
    expect(res.status).toBe(409);
    expect((await res.json()) as { error: string }).toEqual({
      error: "slot has no draft to submit",
    });
  });

  it("404s an unknown slot", () => {
    expect(handleSubmitSlot("ghost-slot", deps()).status).toBe(404);
  });
});

describe("handleRollbackSlot", () => {
  it("rolls a published slot back to its previous version", async () => {
    const res = handleRollbackSlot("business-hours", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slot: PolicySlot };
    expect(body.slot.status).toBe("published");
    expect(body.slot.publishedText).toBe("Open Mon–Fri 9am–5pm.");
  });

  it("409s when there is no previous published version", async () => {
    const res = handleRollbackSlot("payment-methods", deps());
    expect(res.status).toBe(409);
  });

  it("404s an unknown slot", () => {
    expect(handleRollbackSlot("ghost-slot", deps()).status).toBe(404);
  });
});

// --- Per-profile API cutover (ADR-0141/0145 Increment 6) ---------------------
// The knowledge-slot routes dispatch toee_knowledge_ops to the per-profile API
// when HERMES_ADMIN_API_URL/TOKEN are configured. These assert the dispatched
// envelope (tool/action/params + actor on writes), the snake_case->PolicySlot
// mapping, per-error-class status (conflict->409, not_found->404), and the
// fail-closed actor guard (a write with no actor never dispatches the mutation).

const apiSlotRow = {
  slot_id: "business-hours",
  title: "Business hours and service boundaries",
  status: "draft",
  draft_text: "Open Mon-Fri 9-5",
  published_text: null,
  owner: "ops-lead",
  review_date: null,
  has_gap_prompt: false,
};

const WRITE_ACTOR = "seed-supervisor";

type SentDispatch = {
  tool: string;
  action: string;
  params: Record<string, unknown>;
  actor_account_id?: string;
};

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  actorAccountId?: string,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://admin.internal",
    token: "tok",
    actorAccountId,
    fetchImpl,
  });
}

function writeClient(
  data: unknown,
  capture?: (sent: SentDispatch) => void,
): HermesApiClient {
  return apiClient(async (_url, init) => {
    const sent = JSON.parse(init.body as string) as SentDispatch;
    capture?.(sent);
    return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
  }, WRITE_ACTOR);
}

function denyOn(action: string, errorClass: string): HermesApiClient {
  return apiClient(async (_url, init) => {
    const sent = JSON.parse(init.body as string) as SentDispatch;
    if (sent.action === action) {
      return new Response(
        JSON.stringify({ ok: false, error: { class: errorClass, message: "no" } }),
        { status: 200 },
      );
    }
    return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
  }, WRITE_ACTOR);
}

// No actor baked in: governed writes must be refused before the mutation fires.
function actorlessClient(seen: string[]): HermesApiClient {
  return apiClient(async (_url, init) => {
    const sent = JSON.parse(init.body as string) as SentDispatch;
    seen.push(sent.action);
    return new Response(
      JSON.stringify({ ok: true, data: { slot: apiSlotRow } }),
      { status: 200 },
    );
  });
}

function putReqBody(body: unknown): Request {
  return new Request("http://localhost/api/admin/knowledge/slots/business-hours", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleListSlotsViaApi", () => {
  it("maps datastore rows onto PolicySlot", async () => {
    const client = apiClient(async () =>
      new Response(JSON.stringify({ ok: true, data: { slots: [apiSlotRow] } }), {
        status: 200,
      }),
    );
    const res = await handleListSlotsViaApi(client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slots: PolicySlot[] };
    expect(body.slots).toEqual([
      {
        slotId: "business-hours",
        title: "Business hours and service boundaries",
        status: "draft",
        draftText: "Open Mon-Fri 9-5",
        publishedText: null,
        owner: "ops-lead",
        reviewDate: null,
        hasGapPrompt: false,
      },
    ]);
  });

  it("maps a governed error to its per-class status", async () => {
    const client = apiClient(async () =>
      new Response(
        JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
        { status: 200 },
      ),
    );
    expect((await handleListSlotsViaApi(client)).status).toBe(403);
  });
});

describe("handleSaveDraftViaApi", () => {
  it("dispatches update_policy_slot with the slot id, provided fields, and actor", async () => {
    let sent: SentDispatch | null = null;
    const client = writeClient({ slot: apiSlotRow }, (s) => {
      sent = s;
    });
    const res = await handleSaveDraftViaApi(
      putReqBody({ draftText: "Open Mon-Fri 9-5", owner: "ops-lead" }),
      "business-hours",
      client,
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slot: PolicySlot };
    expect(body.slot.status).toBe("draft");
    const s = sent as SentDispatch | null;
    expect(s?.tool).toBe("toee_knowledge_ops");
    expect(s?.action).toBe("update_policy_slot");
    expect(s?.params).toEqual({
      slot_id: "business-hours",
      draft_text: "Open Mon-Fri 9-5",
      owner: "ops-lead",
    });
    expect(s?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("refuses to dispatch a write with no attributed actor (403)", async () => {
    const seen: string[] = [];
    const res = await handleSaveDraftViaApi(
      putReqBody({ draftText: "x" }),
      "business-hours",
      actorlessClient(seen),
    );
    expect(res.status).toBe(403);
    expect(seen).toEqual([]);
  });

  it("404s an unknown slot (governed not_found)", async () => {
    const res = await handleSaveDraftViaApi(
      putReqBody({ draftText: "x" }),
      "ghost-slot",
      denyOn("update_policy_slot", "not_found"),
    );
    expect(res.status).toBe(404);
  });
});

describe("handleSubmitSlotViaApi", () => {
  it("dispatches submit_for_eval with the slot id and actor", async () => {
    let sent: SentDispatch | null = null;
    const client = writeClient(
      { slot: { ...apiSlotRow, status: "pending_eval" } },
      (s) => {
        sent = s;
      },
    );
    const res = await handleSubmitSlotViaApi("business-hours", client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slot: PolicySlot };
    expect(body.slot.status).toBe("pending_eval");
    const s = sent as SentDispatch | null;
    expect(s?.action).toBe("submit_for_eval");
    expect(s?.params).toEqual({ slot_id: "business-hours" });
    expect(s?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("409s when the slot has no draft (governed conflict)", async () => {
    const res = await handleSubmitSlotViaApi(
      "returns-exchanges",
      denyOn("submit_for_eval", "conflict"),
    );
    expect(res.status).toBe(409);
  });

  it("404s an unknown slot (governed not_found)", async () => {
    const res = await handleSubmitSlotViaApi(
      "ghost-slot",
      denyOn("submit_for_eval", "not_found"),
    );
    expect(res.status).toBe(404);
  });
});

describe("handleRollbackSlotViaApi", () => {
  it("dispatches rollback_published_policy with the slot id and actor", async () => {
    let sent: SentDispatch | null = null;
    const client = writeClient(
      { slot: { ...apiSlotRow, status: "published", published_text: "prior" } },
      (s) => {
        sent = s;
      },
    );
    const res = await handleRollbackSlotViaApi("business-hours", client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slot: PolicySlot };
    expect(body.slot.status).toBe("published");
    const s = sent as SentDispatch | null;
    expect(s?.action).toBe("rollback_published_policy");
    expect(s?.params).toEqual({ slot_id: "business-hours" });
    expect(s?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("409s when there is no previous published version (governed conflict)", async () => {
    const res = await handleRollbackSlotViaApi(
      "payment-methods",
      denyOn("rollback_published_policy", "conflict"),
    );
    expect(res.status).toBe(409);
  });
});

// --- S11: corpus status + retrieval probe (FR-6) ------------------------------

describe("handleGetCorpusStatusViaApi", () => {
  it("dispatches get_corpus_status and maps the snake_case payload", async () => {
    let sent: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      sent = JSON.parse(init.body as string) as SentDispatch;
      return new Response(
        JSON.stringify({
          ok: true,
          data: {
            doc_count: 27,
            chunk_count: 167,
            last_ingest_at: "2026-07-01T12:00:00+00:00",
            by_type: [
              { page_type: "faq", count: 40 },
              { page_type: "policy", count: 127 },
            ],
          },
        }),
        { status: 200 },
      );
    });

    const res = await handleGetCorpusStatusViaApi(client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { status: unknown };
    expect(body.status).toEqual({
      docCount: 27,
      chunkCount: 167,
      lastIngestAt: "2026-07-01T12:00:00+00:00",
      byType: [
        { pageType: "faq", count: 40 },
        { pageType: "policy", count: 127 },
      ],
      // 0.0.4 S04: null until a re-ingest has been queued.
      lastIngestJob: null,
    });
    const s = sent as SentDispatch | null;
    expect(s?.tool).toBe("toee_knowledge_ops");
    expect(s?.action).toBe("get_corpus_status");
  });

  it("maps a governed error to its per-class status", async () => {
    const client = apiClient(async () =>
      new Response(
        JSON.stringify({ ok: false, error: { class: "configuration_missing", message: "no" } }),
        { status: 200 },
      ),
    );
    expect((await handleGetCorpusStatusViaApi(client)).status).toBe(503);
  });
});

function probeReq(body: unknown): Request {
  return new Request("http://localhost/api/admin/knowledge/probe", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleProbeQueryViaApi", () => {
  it("dispatches search_public_site with the query and maps results", async () => {
    let sent: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      sent = JSON.parse(init.body as string) as SentDispatch;
      return new Response(
        JSON.stringify({
          ok: true,
          data: {
            results: [
              {
                title: "Return Policy",
                url: "https://example.test/returns",
                snippet: "Tires may be returned within 30 days.",
                chunk_text: "Tires may be returned within 30 days.",
              },
            ],
          },
        }),
        { status: 200 },
      );
    });

    const res = await handleProbeQueryViaApi(probeReq({ query: "return policy" }), client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { results: unknown };
    expect(body.results).toEqual([
      {
        title: "Return Policy",
        url: "https://example.test/returns",
        snippet: "Tires may be returned within 30 days.",
      },
    ]);
    const s = sent as SentDispatch | null;
    expect(s?.tool).toBe("toee_knowledge_search");
    expect(s?.action).toBe("search_public_site");
    expect(s?.params).toEqual({ query: "return policy" });
  });

  it("returns an empty list on the governed no-match shape", async () => {
    const client = apiClient(async () =>
      new Response(JSON.stringify({ ok: true, data: { results: [] } }), { status: 200 }),
    );
    const res = await handleProbeQueryViaApi(probeReq({ query: "nothing matches" }), client);
    const body = (await res.json()) as { results: unknown };
    expect(body.results).toEqual([]);
  });

  it("400s a blank query without dispatching", async () => {
    const seen: string[] = [];
    const client = apiClient(async (_url, init) => {
      const sent = JSON.parse(init.body as string) as SentDispatch;
      seen.push(sent.action);
      return new Response(JSON.stringify({ ok: true, data: { results: [] } }), { status: 200 });
    });
    const res = await handleProbeQueryViaApi(probeReq({ query: "   " }), client);
    expect(res.status).toBe(400);
    expect(seen).toEqual([]);
  });

  it("maps a governed error to its per-class status", async () => {
    const client = apiClient(async () =>
      new Response(
        JSON.stringify({ ok: false, error: { class: "unexpected_error", message: "no" } }),
        { status: 200 },
      ),
    );
    const res = await handleProbeQueryViaApi(probeReq({ query: "x" }), client);
    expect(res.status).toBe(502);
  });
});

// --- 0.0.4 S04: real re-ingest enqueue + status readback (FR-11) --------------

describe("handleTriggerReingestViaApi", () => {
  it("dispatchWrites enqueue_corpus_reingest and returns the job receipt", async () => {
    let sent: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      sent = JSON.parse(init.body as string) as SentDispatch;
      return new Response(
        JSON.stringify({ ok: true, data: { job_id: "job_ing1", status: "queued" } }),
        { status: 200 },
      );
    }, WRITE_ACTOR);

    const res = await handleTriggerReingestViaApi(client);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ jobId: "job_ing1", status: "queued" });
    const s2 = sent as SentDispatch | null;
    expect(s2?.tool).toBe("toee_knowledge_ops");
    expect(s2?.action).toBe("enqueue_corpus_reingest");
    // A corpus wipe-and-reload never lands unattributed.
    expect(s2?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("refuses a write with no attributed actor before the network call", async () => {
    const client = apiClient(
      async () => new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 }),
      "",
    );
    const res = await handleTriggerReingestViaApi(client);
    expect(res.status).toBe(403);
  });

  it("accepts the mock backend's null job id (there is no `job` table behind it)", async () => {
    const client = apiClient(
      async () =>
        new Response(JSON.stringify({ ok: true, data: { job_id: null, status: "unavailable" } }), {
          status: 200,
        }),
      WRITE_ACTOR,
    );
    const res = await handleTriggerReingestViaApi(client);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ jobId: null, status: "unavailable" });
  });

  it("rejects a receipt with no status instead of defaulting it to 'queued'", async () => {
    // S04 fix wave 1, finding 5: aligned with retention.ts's mapRetentionSweepQueued.
    // A defaulted status would show a plausible "queued" panel over a backend that
    // never queued anything.
    const client = apiClient(
      async () =>
        new Response(JSON.stringify({ ok: true, data: { job_id: "job_x" } }), { status: 200 }),
      WRITE_ACTOR,
    );
    const res = await handleTriggerReingestViaApi(client);
    expect(res.status).toBe(502);
  });
});

describe("get_corpus_status's last_ingest_job readback", () => {
  it("maps the queued job so the panel can show it", async () => {
    const client = apiClient(async () =>
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            doc_count: 0,
            chunk_count: 0,
            last_ingest_at: null,
            by_type: [],
            last_ingest_job: {
              job_id: "job_ing1",
              status: "dead",
              attempts: 1,
              last_error: "RuntimeError: fastembed OOM",
              queued_at: "2026-07-21T08:00:00+00:00",
              updated_at: "2026-07-21T08:01:00+00:00",
            },
          },
        }),
        { status: 200 },
      ),
    );

    const res = await handleGetCorpusStatusViaApi(client);
    const body = (await res.json()) as { status: { lastIngestJob: unknown } };
    expect(body.status.lastIngestJob).toEqual({
      jobId: "job_ing1",
      status: "dead",
      attempts: 1,
      lastError: "RuntimeError: fastembed OOM",
      queuedAt: "2026-07-21T08:00:00+00:00",
      updatedAt: "2026-07-21T08:01:00+00:00",
    });
  });
});
