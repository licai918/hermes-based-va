import {
  clearMemorySlot,
  confirmExperience,
  createAccount,
  disableAccount,
  getCorpusStatus,
  getMemoryAudit,
  getRetentionStatus,
  getRun,
  listAccounts,
  listAgentExperience,
  listRuns,
  listSlots,
  probeKnowledge,
  promote,
  rejectExperience,
  rollbackSlot,
  saveDraft,
  signOff,
  submitSlot,
  triggerRetentionSweep,
  updateRole,
} from "./admin-client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body, status));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("admin-client knowledge", () => {
  it("listSlots GETs the slots endpoint and unwraps slots", async () => {
    const slot = { slotId: "business-hours", status: "published" };
    const fetchMock = stubFetch({ slots: [slot] });

    await expect(listSlots()).resolves.toEqual([slot]);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/knowledge/slots", {
      headers: { accept: "application/json" },
    });
  });

  it("saveDraft PUTs the patch body and unwraps slot", async () => {
    const slot = { slotId: "returns-exchanges", status: "draft" };
    const fetchMock = stubFetch({ slot });

    await expect(
      saveDraft("returns-exchanges", {
        draftText: "hello",
        owner: "ops",
        reviewDate: "2026-09-01",
      }),
    ).resolves.toEqual(slot);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/knowledge/slots/returns-exchanges", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        draftText: "hello",
        owner: "ops",
        reviewDate: "2026-09-01",
      }),
    });
  });

  it("submitSlot POSTs the submit endpoint with no body", async () => {
    const slot = { slotId: "returns-exchanges", status: "pending_eval" };
    const fetchMock = stubFetch({ slot });

    await expect(submitSlot("returns-exchanges")).resolves.toEqual(slot);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/knowledge/slots/returns-exchanges/submit",
      { method: "POST", headers: { "content-type": "application/json" }, body: undefined },
    );
  });

  it("submitSlot throws ApiError carrying the 409 message", async () => {
    stubFetch({ error: "slot has no draft to submit" }, 409);
    await expect(submitSlot("returns-exchanges")).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      message: "slot has no draft to submit",
    });
  });

  it("rollbackSlot POSTs the rollback endpoint", async () => {
    const slot = { slotId: "business-hours", status: "published" };
    const fetchMock = stubFetch({ slot });

    await expect(rollbackSlot("business-hours")).resolves.toEqual(slot);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/knowledge/slots/business-hours/rollback",
      { method: "POST", headers: { "content-type": "application/json" }, body: undefined },
    );
  });

  it("getCorpusStatus GETs the corpus-status endpoint and unwraps status", async () => {
    const status = { docCount: 27, chunkCount: 167, lastIngestAt: null, byType: [] };
    const fetchMock = stubFetch({ status });

    await expect(getCorpusStatus()).resolves.toEqual(status);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/knowledge/corpus-status", {
      headers: { accept: "application/json" },
    });
  });

  it("probeKnowledge POSTs the query and unwraps results", async () => {
    const results = [{ title: "Return Policy", url: null, snippet: "..." }];
    const fetchMock = stubFetch({ results });

    await expect(probeKnowledge("return policy")).resolves.toEqual(results);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/knowledge/probe", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: "return policy" }),
    });
  });
});

describe("admin-client eval", () => {
  it("listRuns GETs the runs endpoint and unwraps runs", async () => {
    const run = { run_id: "pp-1", suite: "policy_publish" };
    const fetchMock = stubFetch({ runs: [run] });

    await expect(listRuns()).resolves.toEqual([run]);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/eval/runs", {
      headers: { accept: "application/json" },
    });
  });

  it("getRun GETs a single run by id", async () => {
    const run = { run_id: "pp-1" };
    const fetchMock = stubFetch({ run });

    await expect(getRun("pp-1")).resolves.toEqual(run);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/eval/runs/pp-1", {
      headers: { accept: "application/json" },
    });
  });

  it("signOff POSTs the sign-off endpoint", async () => {
    const run = { run_id: "pp-1", signed_off: true };
    const fetchMock = stubFetch({ run });

    await expect(signOff("pp-1")).resolves.toEqual(run);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/eval/runs/pp-1/sign-off", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: undefined,
    });
  });

  it("promote throws ApiError carrying the gate 409 message", async () => {
    stubFetch({ error: "high-severity failures block promotion" }, 409);
    await expect(promote("pp-1")).rejects.toMatchObject({
      status: 409,
      message: "high-severity failures block promotion",
    });
  });
});

describe("admin-client accounts", () => {
  it("listAccounts GETs the accounts endpoint and unwraps accounts", async () => {
    const account = { accountId: "seed-admin", username: "admin" };
    const fetchMock = stubFetch({ accounts: [account] });

    await expect(listAccounts()).resolves.toEqual([account]);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts", {
      headers: { accept: "application/json" },
    });
  });

  it("createAccount returns ok with the created account on 201", async () => {
    const account = { accountId: "new-1", username: "casey" };
    const fetchMock = stubFetch({ account }, 201);

    await expect(
      createAccount({ username: "casey", role: "customer_service_rep", password: "Workbench123!" }),
    ).resolves.toEqual({ ok: true, account });
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        username: "casey",
        role: "customer_service_rep",
        password: "Workbench123!",
      }),
    });
  });

  it("createAccount surfaces the 400 policy errors[] instead of throwing", async () => {
    stubFetch(
      { error: "password does not meet policy", errors: ["too short", "needs a digit"] },
      400,
    );

    await expect(
      createAccount({ username: "casey", role: "customer_service_rep", password: "x" }),
    ).resolves.toEqual({
      ok: false,
      status: 400,
      error: "password does not meet policy",
      errors: ["too short", "needs a digit"],
    });
  });

  it("createAccount surfaces a 409 duplicate as ok:false with the message", async () => {
    stubFetch({ error: "username already exists" }, 409);

    await expect(
      createAccount({ username: "admin", role: "workbench_admin", password: "Workbench123!" }),
    ).resolves.toEqual({
      ok: false,
      status: 409,
      error: "username already exists",
      errors: undefined,
    });
  });

  it("updateRole PATCHes the role body and unwraps account", async () => {
    const account = { accountId: "seed-rep", role: "workbench_supervisor" };
    const fetchMock = stubFetch({ account });

    await expect(updateRole("seed-rep", "workbench_supervisor")).resolves.toEqual(account);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts/seed-rep/role", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ role: "workbench_supervisor" }),
    });
  });

  it("disableAccount POSTs the disable endpoint", async () => {
    const account = { accountId: "seed-rep", status: "disabled" };
    const fetchMock = stubFetch({ account });

    await expect(disableAccount("seed-rep")).resolves.toEqual(account);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts/seed-rep/disable", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: undefined,
    });
  });
});

describe("admin-client memory audit (0.0.3 S20, FR-20)", () => {
  it("getMemoryAudit GETs the memory-audit endpoint with case_id and returns the view", async () => {
    const view = { slots: [], history: [] };
    const fetchMock = stubFetch(view);

    await expect(getMemoryAudit("case_1")).resolves.toEqual(view);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/memory-audit?case_id=case_1", {
      headers: { accept: "application/json" },
    });
  });

  it("clearMemorySlot POSTs the clear endpoint with the slot body", async () => {
    const fetchMock = stubFetch({ slot: "channel_preference", cleared: true });

    await expect(clearMemorySlot("case_1", "channel_preference")).resolves.toEqual({
      slot: "channel_preference",
      cleared: true,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/memory-audit/clear?case_id=case_1",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ slot: "channel_preference" }),
      },
    );
  });
});

describe("admin-client agent experience (0.0.3 S22/S24, FR-23/FR-24)", () => {
  it("listAgentExperience GETs the agent-experience endpoint and unwraps entries", async () => {
    const entry = { id: "aexp_1", kind: "note", status: "proposed" };
    const fetchMock = stubFetch({ entries: [entry] });

    await expect(listAgentExperience()).resolves.toEqual([entry]);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/agent-experience", {
      headers: { accept: "application/json" },
    });
  });

  it("confirmExperience POSTs the confirm endpoint for the entry id and unwraps entry", async () => {
    const entry = { id: "aexp_1", kind: "note", status: "confirmed", deciderAccountId: "seed-admin" };
    const fetchMock = stubFetch({ entry });

    await expect(confirmExperience("aexp_1")).resolves.toEqual(entry);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/agent-experience/aexp_1/confirm", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: undefined,
    });
  });

  it("rejectExperience POSTs the reject endpoint for the entry id and unwraps entry", async () => {
    const entry = { id: "aexp_1", kind: "note", status: "rejected", deciderAccountId: "seed-admin" };
    const fetchMock = stubFetch({ entry });

    await expect(rejectExperience("aexp_1")).resolves.toEqual(entry);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/agent-experience/aexp_1/reject", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: undefined,
    });
  });

  it("confirmExperience throws ApiError carrying a governed denial message", async () => {
    stubFetch({ error: "agent_experience entry \"aexp_missing\" not found." }, 404);
    await expect(confirmExperience("aexp_missing")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });
});

describe("admin-client retention sweep (0.0.3 S28, FR-30)", () => {
  it("getRetentionStatus GETs the retention endpoint and returns the status", async () => {
    const status = {
      lastRunAt: null,
      counts: { verified: 0, provisional: 0 },
      totalDeleted: 0,
      windowsDays: { verified: 730, provisional: 90 },
    };
    const fetchMock = stubFetch(status);

    await expect(getRetentionStatus()).resolves.toEqual(status);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/retention", {
      headers: { accept: "application/json" },
    });
  });

  it("triggerRetentionSweep POSTs the sweep endpoint with no body and returns the result", async () => {
    const result = {
      lastRunAt: "2026-07-21T08:00:00.000000+00:00",
      runAt: "2026-07-21T08:00:00.000000+00:00",
      counts: { verified: 1, provisional: 2 },
      totalDeleted: 3,
      windowsDays: { verified: 730, provisional: 90 },
    };
    const fetchMock = stubFetch(result);

    await expect(triggerRetentionSweep()).resolves.toEqual(result);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/retention/sweep", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: undefined,
    });
  });

  it("triggerRetentionSweep throws ApiError carrying a governed denial message", async () => {
    stubFetch({ error: "a governed case write requires an attributed actor" }, 403);
    await expect(triggerRetentionSweep()).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
    });
  });
});
