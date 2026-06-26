import { beforeEach, describe, expect, it } from "vitest";
import { WORKBENCH_ROLES } from "@toee/shared";
import { createInMemoryAccountStore } from "../../auth/account-store";
import type { WorkbenchSession } from "../../auth/session";
import {
  createEvalSeed,
  createInMemoryEvalStore,
  type EvalRunReport,
  type EvalRunSummary,
  type EvalStore,
} from "../../gateway/eval-store";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { createInMemoryKnowledgeStore } from "../../gateway/knowledge-store";
import type { AdminDeps } from "./deps";
import {
  handleGetRun,
  handleGetRunViaApi,
  handleListRuns,
  handleListRunsViaApi,
  handlePromote,
  handlePromoteViaApi,
  handleSignOff,
  handleSignOffViaApi,
} from "./eval";

const NOW = 1_700_000_000_000;

// Knowledge + account stores are untouched by the eval handlers; build once.
const knowledge = createInMemoryKnowledgeStore();
const accounts = createInMemoryAccountStore(0);

let evalStore: EvalStore;

beforeEach(() => {
  evalStore = createInMemoryEvalStore(createEvalSeed());
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

describe("handleListRuns", () => {
  it("returns every seeded run", async () => {
    const res = handleListRuns(deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { runs: EvalRunSummary[] };
    expect(body.runs).toHaveLength(3);
    expect(body.runs.map((r) => r.run_id)).toContain("pp-20260602");
  });
});

describe("handleGetRun", () => {
  it("returns the full report", async () => {
    const res = handleGetRun("tfl-20260603", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { run: EvalRunReport };
    expect(body.run.run_id).toBe("tfl-20260603");
  });

  it("404s an unknown run", () => {
    expect(handleGetRun("nope", deps()).status).toBe(404);
  });
});

describe("handleSignOff", () => {
  it("409s not_required for a passing run with no medium failures", async () => {
    const res = handleSignOff("tfl-20260603", deps());
    expect(res.status).toBe(409);
    expect((await res.json()) as { error: string }).toEqual({
      error: "no medium sign-off required",
    });
  });

  it("409s failed_high when a high-severity failure blocks sign-off", async () => {
    const res = handleSignOff("tfl-20260530", deps());
    expect(res.status).toBe(409);
    expect((await res.json()) as { error: string }).toEqual({
      error: "high-severity failures block sign-off",
    });
  });

  it("signs off a medium policy_publish run", async () => {
    const res = handleSignOff("pp-20260602", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { run: EvalRunReport };
    expect(body.run.signed_off).toBe(true);
  });

  it("404s an unknown run", () => {
    expect(handleSignOff("nope", deps()).status).toBe(404);
  });
});

describe("handlePromote", () => {
  it("409s not_promotable for a non policy_publish run", async () => {
    const res = handlePromote("tfl-20260603", deps());
    expect(res.status).toBe(409);
    expect((await res.json()) as { error: string }).toEqual({
      error: "run is not a promotable policy_publish run",
    });
  });

  it("409s signoff_required before the medium failure is signed off", async () => {
    const res = handlePromote("pp-20260602", deps());
    expect(res.status).toBe(409);
    expect((await res.json()) as { error: string }).toEqual({
      error: "medium failures must be signed off first",
    });
  });

  it("promotes after the medium failure is signed off", async () => {
    const d = deps();
    expect(handleSignOff("pp-20260602", d).status).toBe(200);
    const res = handlePromote("pp-20260602", d);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { run: EvalRunReport };
    expect(body.run.promoted).toBe(true);
  });

  it("404s an unknown run", () => {
    expect(handlePromote("nope", deps()).status).toBe(404);
  });
});

// --- Per-profile API cutover (ADR-0141/0146 Increment 7) ---------------------
// The eval routes dispatch toee_eval_review to the per-profile API when
// HERMES_ADMIN_API_URL/TOKEN are configured. These assert the dispatched envelope
// (tool/action/params + actor on writes), the report/summary guards, per-error-
// class status (conflict->409, not_found->404), and the fail-closed actor guard.

const apiSummaryRow = {
  run_id: "pp-1",
  suite: "policy_publish",
  timestamp: "2026-06-02T00:00:00Z",
  passed: false,
  failed_high: 0,
  failed_medium: 1,
  knowledge_version: "kb-v2",
  prompt_version: "persona-v1",
};

const apiReportRow = {
  run_id: "pp-1",
  suite: "policy_publish",
  model_slug: "deepseek/deepseek-v4-pro",
  prompt_version: "persona-v1",
  knowledge_version: "kb-v2",
  timestamp: "2026-06-02T00:00:00Z",
  scenarios: [
    {
      scenario_id: "returns-policy-edge",
      passed: false,
      failed_assertions: ["tone_softening_expected"],
      severity: "medium",
    },
  ],
  summary: { total: 10, passed: 9, failed_high: 0, failed_medium: 1 },
  signoff_required: true,
  signed_off: true,
  promoted: false,
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
      JSON.stringify({ ok: true, data: { run: apiReportRow } }),
      { status: 200 },
    );
  });
}

describe("handleListRunsViaApi", () => {
  it("maps datastore rows onto EvalRunSummary", async () => {
    const client = apiClient(async () =>
      new Response(JSON.stringify({ ok: true, data: { runs: [apiSummaryRow] } }), {
        status: 200,
      }),
    );
    const res = await handleListRunsViaApi(client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { runs: EvalRunSummary[] };
    expect(body.runs).toEqual([apiSummaryRow]);
  });

  it("maps a governed error to its per-class status", async () => {
    const client = apiClient(async () =>
      new Response(
        JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
        { status: 200 },
      ),
    );
    expect((await handleListRunsViaApi(client)).status).toBe(403);
  });
});

describe("handleGetRunViaApi", () => {
  it("dispatches get_eval_run and maps the full report", async () => {
    let sent: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      sent = JSON.parse(init.body as string) as SentDispatch;
      return new Response(JSON.stringify({ ok: true, data: { run: apiReportRow } }), {
        status: 200,
      });
    });
    const res = await handleGetRunViaApi("pp-1", client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { run: EvalRunReport };
    expect(body.run.run_id).toBe("pp-1");
    expect(body.run.signed_off).toBe(true);
    expect(body.run.summary.failed_medium).toBe(1);
    const s = sent as SentDispatch | null;
    expect(s?.action).toBe("get_eval_run");
    expect(s?.params).toEqual({ run_id: "pp-1" });
  });

  it("404s an unknown run (governed not_found)", async () => {
    const res = await handleGetRunViaApi("nope", denyOn("get_eval_run", "not_found"));
    expect(res.status).toBe(404);
  });
});

describe("handleSignOffViaApi", () => {
  it("dispatches sign_off_medium_failure with the run id and actor", async () => {
    let sent: SentDispatch | null = null;
    const client = writeClient({ run: apiReportRow }, (s) => {
      sent = s;
    });
    const res = await handleSignOffViaApi("pp-1", client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { run: EvalRunReport };
    expect(body.run.signed_off).toBe(true);
    const s = sent as SentDispatch | null;
    expect(s?.tool).toBe("toee_eval_review");
    expect(s?.action).toBe("sign_off_medium_failure");
    expect(s?.params).toEqual({ run_id: "pp-1" });
    expect(s?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("409s a governed conflict", async () => {
    const res = await handleSignOffViaApi(
      "tfl-1",
      denyOn("sign_off_medium_failure", "conflict"),
    );
    expect(res.status).toBe(409);
  });

  it("refuses to dispatch a write with no attributed actor (403)", async () => {
    const seen: string[] = [];
    const res = await handleSignOffViaApi("pp-1", actorlessClient(seen));
    expect(res.status).toBe(403);
    expect(seen).toEqual([]);
  });
});

describe("handlePromoteViaApi", () => {
  it("dispatches promote_pending_policy with the run id and actor", async () => {
    let sent: SentDispatch | null = null;
    const client = writeClient({ run: { ...apiReportRow, promoted: true } }, (s) => {
      sent = s;
    });
    const res = await handlePromoteViaApi("pp-1", client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { run: EvalRunReport };
    expect(body.run.promoted).toBe(true);
    const s = sent as SentDispatch | null;
    expect(s?.action).toBe("promote_pending_policy");
    expect(s?.params).toEqual({ run_id: "pp-1" });
    expect(s?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("409s a governed conflict (not promotable / signoff required)", async () => {
    const res = await handlePromoteViaApi(
      "tfl-1",
      denyOn("promote_pending_policy", "conflict"),
    );
    expect(res.status).toBe(409);
  });

  it("refuses to dispatch a write with no attributed actor (403)", async () => {
    const seen: string[] = [];
    const res = await handlePromoteViaApi("pp-1", actorlessClient(seen));
    expect(res.status).toBe(403);
    expect(seen).toEqual([]);
  });
});
