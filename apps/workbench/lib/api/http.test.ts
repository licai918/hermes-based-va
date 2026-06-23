import { ApiError, getJson, sendJson } from "./http";

afterEach(() => vi.unstubAllGlobals());

describe("getJson", () => {
  it("returns the parsed body on a 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ cases: [1, 2] }), { status: 200 }),
      ),
    );
    await expect(getJson<{ cases: number[] }>("/api/copilot/cases")).resolves.toEqual({
      cases: [1, 2],
    });
  });

  it("throws an ApiError carrying status + server message on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "forbidden" }), { status: 403 }),
      ),
    );
    await expect(getJson("/api/admin/accounts")).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
      message: "forbidden",
    });
  });

  it("falls back to a generic message when the body has no error field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("oops", { status: 500 })),
    );
    await expect(getJson("/x")).rejects.toMatchObject({
      status: 500,
      message: "request failed (500)",
    });
  });
});

describe("sendJson", () => {
  it("posts a JSON body and returns the parsed response", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      sendJson("POST", "/api/copilot/cases/c1/claim", { foo: "bar" }),
    ).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/cases/c1/claim", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ foo: "bar" }),
    });
  });

  it("omits the body when no payload is given", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await sendJson("POST", "/api/copilot/cases/c1/resolve");
    expect(fetchMock).toHaveBeenCalledWith("/api/copilot/cases/c1/resolve", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: undefined,
    });
  });

  it("throws ApiError on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "case not found" }), { status: 404 }),
      ),
    );
    await expect(sendJson("POST", "/api/copilot/cases/none/claim")).rejects.toMatchObject(
      { status: 404, message: "case not found" },
    );
    expect(ApiError).toBeDefined();
  });
});
