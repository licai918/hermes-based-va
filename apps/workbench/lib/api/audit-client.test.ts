import {
  getAutoHandled,
  getSalesOutreach,
  listAutoHandled,
  listSalesOutreach,
} from "./audit-client";

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

const ACCEPT = { headers: { accept: "application/json" } };

describe("audit-client", () => {
  it("listAutoHandled GETs the auto-handled collection", async () => {
    const fetchMock = stubFetch({ records: [] });
    await expect(listAutoHandled()).resolves.toEqual({ records: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/copilot/audit/auto-handled",
      ACCEPT,
    );
  });

  it("getAutoHandled GETs a single record by id", async () => {
    const fetchMock = stubFetch({ record: { recordId: "rec-1" } });
    await getAutoHandled("rec-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/copilot/audit/auto-handled/rec-1",
      ACCEPT,
    );
  });

  it("getAutoHandled throws ApiError on 404", async () => {
    stubFetch({ error: "record not found" }, 404);
    await expect(getAutoHandled("missing")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });

  it("listSalesOutreach GETs the sales-outreach collection", async () => {
    const fetchMock = stubFetch({ cases: [] });
    await expect(listSalesOutreach()).resolves.toEqual({ cases: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/copilot/audit/sales-outreach",
      ACCEPT,
    );
  });

  it("getSalesOutreach GETs a single case by id", async () => {
    const fetchMock = stubFetch({ case: { caseId: "case-1" } });
    await getSalesOutreach("case-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/copilot/audit/sales-outreach/case-1",
      ACCEPT,
    );
  });

  it("getSalesOutreach throws ApiError on 404", async () => {
    stubFetch({ error: "not a sales outreach case" }, 404);
    await expect(getSalesOutreach("missing")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });
});
