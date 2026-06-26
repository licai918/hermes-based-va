import {
  assignCase,
  chat,
  claimCase,
  draft,
  getThread,
  listCases,
  normalizeDraft,
  resolveCase,
  sendTextline,
  setContactReason,
  setPriority,
} from "./copilot-client";

function ok(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200 });
}

afterEach(() => vi.unstubAllGlobals());

describe("listCases", () => {
  it("GETs the queue with repeated status params + assignee mode", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ cases: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await listCases({ statuses: ["open", "in_progress"], assignee: "all" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/copilot/cases?status=open&status=in_progress&assignee=all",
      { headers: { accept: "application/json" } },
    );
  });

  it("omits the query string entirely when no filter is given", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ cases: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await listCases();

    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/cases", {
      headers: { accept: "application/json" },
    });
  });
});

describe("read wrappers", () => {
  it("getThread hits the thread endpoint and returns case + messages", async () => {
    const payload = { case: { caseId: "c1" }, messages: [{ messageId: "m1" }] };
    const fetchMock = vi.fn().mockResolvedValue(ok(payload));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getThread("c1")).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/cases/c1/thread", {
      headers: { accept: "application/json" },
    });
  });
});

describe("mutation wrappers", () => {
  it("claimCase POSTs with no body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ case: { caseId: "c1" } }));
    vi.stubGlobal("fetch", fetchMock);

    await claimCase("c1");

    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/cases/c1/claim", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: undefined,
    });
  });

  it("assignCase POSTs the assignee account id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ case: { caseId: "c1" } }));
    vi.stubGlobal("fetch", fetchMock);

    await assignCase("c1", "acct-2");

    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/cases/c1/assign", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ assigneeAccountId: "acct-2" }),
    });
  });

  it("resolveCase POSTs the resolve endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ case: { caseId: "c1" } }));
    vi.stubGlobal("fetch", fetchMock);

    await resolveCase("c1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/copilot/cases/c1/resolve",
      expect.objectContaining({ method: "POST", body: undefined }),
    );
  });

  it("setPriority POSTs the urgent boolean", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ case: { caseId: "c1" } }));
    vi.stubGlobal("fetch", fetchMock);

    await setPriority("c1", true);

    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/cases/c1/priority", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ urgent: true }),
    });
  });

  it("setContactReason POSTs the new reason", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ case: { caseId: "c1" } }));
    vi.stubGlobal("fetch", fetchMock);

    await setContactReason("c1", "order_status");

    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/cases/c1/contact-reason", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ contactReason: "order_status" }),
    });
  });

  it("draft POSTs to the kind-specific endpoint with caseId + prompt", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ draft: "hi" }));
    vi.stubGlobal("fetch", fetchMock);

    await draft("email", "c1", "be brief");

    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/drafts/email", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ caseId: "c1", prompt: "be brief" }),
    });
  });

  it("draft omits prompt when not provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ draft: "hi" }));
    vi.stubGlobal("fetch", fetchMock);

    await draft("note", "c1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/copilot/drafts/note",
      expect.objectContaining({ body: JSON.stringify({ caseId: "c1" }) }),
    );
  });

  it("chat POSTs the message (+ optional caseId)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(ok({ state: "ready", reply: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await chat("draft an sms", "c1");

    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ caseId: "c1", message: "draft an sms" }),
    });
  });

  it("sendTextline POSTs caseId + body (+ optional mediaUrl)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ message: { messageId: "m9" } }));
    vi.stubGlobal("fetch", fetchMock);

    await sendTextline("c1", "Your tires are ready");

    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/messages/textline/send", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ caseId: "c1", body: "Your tires are ready" }),
    });
  });

  it("propagates ApiError from the shared http layer (e.g. rep assign 403)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "forbidden" }), { status: 403 }),
      ),
    );

    await expect(assignCase("c1", "acct-2")).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
      message: "forbidden",
    });
  });
});

describe("normalizeDraft", () => {
  it("returns a string draft as-is", () => {
    expect(normalizeDraft("hello")).toBe("hello");
  });

  it("reads the .draft field of an object", () => {
    expect(normalizeDraft({ draft: "from draft" })).toBe("from draft");
  });

  it("falls back to .body", () => {
    expect(normalizeDraft({ body: "from body" })).toBe("from body");
  });

  it("stringifies anything else defensively", () => {
    expect(normalizeDraft({ weird: 1 })).toBe(JSON.stringify({ weird: 1 }));
  });
});
