import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { WORKBENCH_ROLES } from "@toee/shared";
import {
  createSessionToken,
  SESSION_COOKIE_NAME,
  SESSION_IDLE_MS,
  type WorkbenchSession,
} from "../auth/session";
import { parseCookies, withSession } from "./with-session";
import { HermesApiError } from "../gateway/hermes-api-client";

const SECRET = "with-session-test-secret";
const original = process.env.WORKBENCH_SESSION_SECRET;

beforeAll(() => {
  process.env.WORKBENCH_SESSION_SECRET = SECRET;
});
afterAll(() => {
  if (original === undefined) delete process.env.WORKBENCH_SESSION_SECRET;
  else process.env.WORKBENCH_SESSION_SECRET = original;
});

function repSession(
  overrides: Partial<WorkbenchSession> = {},
): WorkbenchSession {
  return {
    accountId: "acc-rep",
    username: "rep",
    role: WORKBENCH_ROLES.rep,
    lastActivityAt: Date.now(),
    ...overrides,
  };
}

async function cookieRequest(
  url: string,
  session: WorkbenchSession,
): Promise<Request> {
  const token = await createSessionToken(session, SECRET);
  return new Request(url, {
    headers: { cookie: `${SESSION_COOKIE_NAME}=${token}` },
  });
}

describe("parseCookies", () => {
  it("parses a cookie header into a map", () => {
    expect(parseCookies("a=1; b=2")).toEqual({ a: "1", b: "2" });
  });

  it("returns an empty object for null or empty headers", () => {
    expect(parseCookies(null)).toEqual({});
    expect(parseCookies("")).toEqual({});
  });

  it("trims names/values and keeps '=' inside values", () => {
    expect(parseCookies(" token = a.b=c ")).toEqual({ token: "a.b=c" });
  });
});

describe("withSession", () => {
  it("invokes the handler with the session for a valid rep on a copilot path", async () => {
    let received: WorkbenchSession | undefined;
    const guarded = withSession((_req, ctx) => {
      received = ctx.session;
      return new Response("ok", { status: 200 });
    });
    const res = await guarded(
      await cookieRequest("https://wb.test/api/copilot/cases", repSession()),
    );
    expect(res.status).toBe(200);
    expect(received?.username).toBe("rep");
  });

  it("returns 401 when no session cookie is present", async () => {
    const guarded = withSession(() => new Response("ok"));
    const res = await guarded(new Request("https://wb.test/api/copilot/cases"));
    expect(res.status).toBe(401);
  });

  it("returns 403 when a rep hits an admin path", async () => {
    const guarded = withSession(() => new Response("ok"));
    const res = await guarded(
      await cookieRequest("https://wb.test/api/admin/accounts", repSession()),
    );
    expect(res.status).toBe(403);
  });

  it("returns 401 for an expired session", async () => {
    const guarded = withSession(() => new Response("ok"));
    const res = await guarded(
      await cookieRequest(
        "https://wb.test/api/copilot/cases",
        repSession({ lastActivityAt: Date.now() - SESSION_IDLE_MS - 60_000 }),
      ),
    );
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ error: "session expired" });
  });

  it("returns 401 for a tampered cookie", async () => {
    const token = await createSessionToken(repSession(), SECRET);
    const [payload, sig] = token.split(".");
    const flipped = (payload![0] === "A" ? "B" : "A") + payload!.slice(1);
    const req = new Request("https://wb.test/api/copilot/cases", {
      headers: { cookie: `${SESSION_COOKIE_NAME}=${flipped}.${sig}` },
    });
    const guarded = withSession(() => new Response("ok"));
    expect((await guarded(req)).status).toBe(401);
  });

  it("awaits a params promise and forwards it to the handler", async () => {
    let receivedParams: Record<string, string> | undefined;
    const guarded = withSession((_req, ctx) => {
      receivedParams = ctx.params;
      return new Response("ok");
    });
    await guarded(
      await cookieRequest("https://wb.test/api/copilot/cases/42", repSession()),
      { params: Promise.resolve({ id: "42" }) },
    );
    expect(receivedParams).toEqual({ id: "42" });
  });

  it("maps a HermesApiError thrown by the handler to its governed status (not a bare 500)", async () => {
    // A handler's SYNCHRONOUS setup (e.g. new HermesApiClient) can throw outside
    // its own try/catch; withSession's last-resort catch maps it through
    // hermesErrorToProblem so the class-derived status is preserved.
    const guarded = withSession(() => {
      throw new HermesApiError("policy_blocked", "blocked by policy");
    });
    const res = await guarded(
      await cookieRequest("https://wb.test/api/copilot/cases", repSession()),
    );
    expect(res.status).toBe(403);
    expect(await res.json()).toMatchObject({ errorClass: "policy_blocked" });
  });

  it("maps any other throw (or async rejection) to a governed 502, never leaking a bare 500", async () => {
    const sync = withSession(() => {
      throw new Error("boom in synchronous setup");
    });
    const asyncReject = withSession(async () => {
      throw new Error("boom in async body");
    });
    const req1 = await cookieRequest("https://wb.test/api/copilot/cases", repSession());
    const req2 = await cookieRequest("https://wb.test/api/copilot/cases", repSession());
    const [r1, r2] = await Promise.all([sync(req1), asyncReject(req2)]);
    expect(r1.status).toBe(502);
    expect(r2.status).toBe(502);
    expect(await r1.json()).toMatchObject({ errorClass: "unexpected_error" });
  });
});
