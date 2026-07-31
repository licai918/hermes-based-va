// Route test for the Memory Hub aggregate read (0.0.5 S14, FR-21).
//
// Nothing is module-mocked: the real `withSession` runs against a real signed
// cookie and both real `HermesApiClient`s are built from real env, with only
// `fetch` faked -- the same posture as the lexicon route tests. The three things
// this route exists to do that the BFF handler cannot check for itself are the
// admin gate, reaching the RIGHT profile per tool, and being read-only.
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { WORKBENCH_ROLES } from "@toee/shared";
import {
  createSessionToken,
  SESSION_COOKIE_NAME,
  type WorkbenchSession,
} from "@/lib/auth/session";
import * as routeModule from "./route";
import { GET } from "./route";

const SECRET = "memory-hub-route-test-secret";

beforeAll(() => {
  process.env.WORKBENCH_SESSION_SECRET = SECRET;
  process.env.HERMES_COPILOT_API_URL = "http://copilot.internal";
  process.env.HERMES_COPILOT_API_TOKEN = "copilot-tok";
  process.env.HERMES_ADMIN_API_URL = "http://admin.internal";
  process.env.HERMES_ADMIN_API_TOKEN = "admin-tok";
});

afterEach(() => vi.unstubAllGlobals());

type Sent = { url: string; tool: string; action: string; auth: string | null };

function stubDispatch(): Sent[] {
  const sent: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string) as { tool: string; action: string };
      sent.push({
        url,
        tool: body.tool,
        action: body.action,
        auth: new Headers(init.headers).get("authorization"),
      });
      // A governed error is fine here: the handler degrades that layer to
      // "unavailable". These tests are about the gate and the routing, not the
      // payload -- memory-hub.test.ts owns the payload.
      return new Response(
        JSON.stringify({ ok: false, error: { class: "not_found", message: "no data" } }),
        { status: 200 },
      );
    }),
  );
  return sent;
}

function session(overrides: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    accountId: "seed-supervisor",
    username: "supervisor",
    role: WORKBENCH_ROLES.supervisor,
    lastActivityAt: Date.now(),
    ...overrides,
  };
}

async function request(who: WorkbenchSession | null = session()): Promise<Request> {
  const headers = new Headers();
  if (who) {
    headers.set(
      "cookie",
      `${SESSION_COOKIE_NAME}=${await createSessionToken(who, SECRET)}`,
    );
  }
  return new Request("https://wb.test/api/admin/memory-hub", { headers });
}

describe("GET /api/admin/memory-hub", () => {
  it("sends each tool to the profile that allowlists it", async () => {
    const sent = stubDispatch();
    const res = await GET(await request());

    expect(res.status).toBe(200);
    // toee_knowledge_ops is a Supervisor Admin Profile tool; the other four are
    // allowlisted for internal_copilot only. Sending one to the wrong profile is
    // a policy_blocked in production and a silently empty row on this page.
    const byTool = Object.fromEntries(sent.map((s) => [s.tool, s.url]));
    expect(byTool).toEqual({
      toee_agent_experience: "http://copilot.internal/v1/tools:dispatch",
      toee_semantic_lexicon: "http://copilot.internal/v1/tools:dispatch",
      toee_retention: "http://copilot.internal/v1/tools:dispatch",
      toee_metrics: "http://copilot.internal/v1/tools:dispatch",
      toee_knowledge_ops: "http://admin.internal/v1/tools:dispatch",
    });
    expect(sent.find((s) => s.tool === "toee_knowledge_ops")?.auth).toBe(
      "Bearer admin-tok",
    );
  });

  it("still answers 200 when every source fails, so the layer map stays readable", async () => {
    // All five dispatches return a governed error in this harness.
    stubDispatch();
    const res = await GET(await request());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { rows: { layer: string }[] };
    expect(body.rows.map((r) => r.layer)).toEqual([
      "L1",
      "L2",
      "L3",
      "L4",
      "L5",
      "L6",
      "L7",
    ]);
  });

  it("is closed to a rep, and closed before any dispatch", async () => {
    const sent = stubDispatch();
    const res = await GET(
      await request(
        session({ accountId: "acc-rep", username: "rep", role: WORKBENCH_ROLES.rep }),
      ),
    );
    expect(res.status).toBe(403);
    expect(sent).toHaveLength(0);
  });

  it("401s without a session cookie, before any dispatch", async () => {
    const sent = stubDispatch();
    const res = await GET(await request(null));
    expect(res.status).toBe(401);
    expect(sent).toHaveLength(0);
  });

  // FR-21 is a read-only page. A write here would need ADR-0148 governed-action
  // treatment (framework-derived actor, fail-closed policy_blocked, the
  // registered_names() exclusion test); this asserts the slice did not quietly
  // acquire one.
  it("exports a read verb only -- no POST/PATCH/PUT/DELETE", () => {
    expect(Object.keys(routeModule).sort()).toEqual(["GET", "runtime"]);
  });
});
