// Route tests for the whole L7 lexicon route group (0.0.5 S02, FR-3/FR-8).
//
// One file for all three route files -- `/api/admin/lexicon`, `.../[id]` and
// `.../[id]/[decision]` -- because they share every piece of setup and are one
// surface. They were the only new code in S02 with no tests, and they held the
// slice's one real bug (`decision in LEXICON_DECISION_ACTIONS` was true for
// `toString`).
//
// Nothing is module-mocked: the real `withSession` runs against a real signed
// cookie and the real `HermesApiClient` is built from real env, with only
// `fetch` faked. That is deliberate -- these routes exist to do exactly three
// things the BFF handlers cannot check for themselves (gate the session, refuse
// a malformed segment/body before dispatch, and carry the SIGNED-IN account as
// the actor), and a mocked `withSession` would prove none of them.
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { WORKBENCH_ROLES } from "@toee/shared";
import {
  createSessionToken,
  SESSION_COOKIE_NAME,
  type WorkbenchSession,
} from "@/lib/auth/session";
import { GET, POST as POST_LEXICON } from "./route";
import { PATCH } from "./[id]/route";
import { POST as POST_DECISION } from "./[id]/[decision]/route";

const SECRET = "lexicon-route-test-secret";

beforeAll(() => {
  process.env.WORKBENCH_SESSION_SECRET = SECRET;
  process.env.HERMES_COPILOT_API_URL = "http://copilot.internal";
  process.env.HERMES_COPILOT_API_TOKEN = "tok";
});

afterEach(() => vi.unstubAllGlobals());

type Dispatch = {
  tool: string;
  action: string;
  params: Record<string, unknown>;
  actor_account_id?: string;
};

function session(overrides: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    accountId: "seed-supervisor",
    username: "supervisor",
    role: WORKBENCH_ROLES.supervisor,
    lastActivityAt: Date.now(),
    ...overrides,
  };
}

function rawEntry(overrides: Record<string, unknown> = {}) {
  return {
    id: "lex_1",
    domain: "company",
    entry_kind: "alias",
    surface_form: "TOEE",
    canonical_form: "TOEE TIRE",
    status: "proposed",
    provenance: "conversation_confirmed",
    evidence: "Customer wrote TOEE.",
    proposer_context: { case_id: "case_1" },
    pii_redacted: false,
    decider_account_id: null,
    provenance_unattributed: false,
    decided_at: null,
    hit_count: 0,
    created_at: "2026-07-01T10:00:00Z",
    updated_at: "2026-07-01T10:00:00Z",
    ...overrides,
  };
}

// Records every dispatch the route actually made. `sent.length === 0` is the
// assertion that matters for every guard: a refusal must happen BEFORE the
// network call, not be papered over by an upstream error afterwards.
function stubDispatch(data: unknown = rawEntry()): Dispatch[] {
  const sent: Dispatch[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit) => {
      sent.push(JSON.parse(init.body as string) as Dispatch);
      return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
    }),
  );
  return sent;
}

async function request(
  url: string,
  init: RequestInit = {},
  who: WorkbenchSession | null = session(),
): Promise<Request> {
  const headers = new Headers(init.headers);
  if (who) {
    headers.set(
      "cookie",
      `${SESSION_COOKIE_NAME}=${await createSessionToken(who, SECRET)}`,
    );
  }
  return new Request(url, { ...init, headers });
}

function jsonInit(body: unknown, method: string): RequestInit {
  return {
    method,
    headers: { "content-type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  };
}

describe("POST /api/admin/lexicon/[id]/[decision]", () => {
  it.each([
    ["confirm", "confirm_lexicon_entry"],
    ["reject", "reject_lexicon_entry"],
    ["retire", "retire_lexicon_entry"],
  ])("dispatches %s with the signed-in account as the actor", async (
    decision,
    action,
  ) => {
    const sent = stubDispatch();

    const res = await POST_DECISION(
      await request(`https://wb.test/api/admin/lexicon/lex_1/${decision}`, {
        method: "POST",
      }),
      { params: { id: "lex_1", decision } },
    );

    expect(res.status).toBe(200);
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({
      tool: "toee_semantic_lexicon",
      action,
      params: { id: "lex_1" },
      // Never a client-supplied param -- the actor rides the session.
      actor_account_id: "seed-supervisor",
    });
  });

  // The bug: `decision in LEXICON_DECISION_ACTIONS` walks the prototype chain,
  // so these all passed the 404 guard and dispatched a `Function` as an action
  // name -- a confusing 500 instead of a clean 404.
  it.each(["toString", "constructor", "__proto__", "valueOf", "hasOwnProperty"])(
    "404s on the inherited Object property %s without dispatching",
    async (decision) => {
      const sent = stubDispatch();

      const res = await POST_DECISION(
        await request(`https://wb.test/api/admin/lexicon/lex_1/${decision}`, {
          method: "POST",
        }),
        { params: { id: "lex_1", decision } },
      );

      expect(res.status).toBe(404);
      expect(sent).toHaveLength(0);
    },
  );

  it("404s on a plausible-but-unknown decision", async () => {
    const sent = stubDispatch();
    const res = await POST_DECISION(
      await request("https://wb.test/api/admin/lexicon/lex_1/approve", {
        method: "POST",
      }),
      { params: { id: "lex_1", decision: "approve" } },
    );
    expect(res.status).toBe(404);
    expect(sent).toHaveLength(0);
  });

  it("400s on a missing id without dispatching", async () => {
    const sent = stubDispatch();
    const res = await POST_DECISION(
      await request("https://wb.test/api/admin/lexicon//confirm", { method: "POST" }),
      { params: { decision: "confirm" } },
    );
    expect(res.status).toBe(400);
    expect(sent).toHaveLength(0);
  });

  it("is closed to a rep, and closed before the network call", async () => {
    // /admin/* is supervisor+admin (ADR-0093); see lib/auth/access.ts for why
    // the lexicon console is NOT in the narrower integrations-only tier.
    const sent = stubDispatch();
    const res = await POST_DECISION(
      await request(
        "https://wb.test/api/admin/lexicon/lex_1/confirm",
        { method: "POST" },
        session({ accountId: "acc-rep", username: "rep", role: WORKBENCH_ROLES.rep }),
      ),
      { params: { id: "lex_1", decision: "confirm" } },
    );
    expect(res.status).toBe(403);
    expect(sent).toHaveLength(0);
  });

  it("401s without a session cookie", async () => {
    const sent = stubDispatch();
    const res = await POST_DECISION(
      await request(
        "https://wb.test/api/admin/lexicon/lex_1/confirm",
        { method: "POST" },
        null,
      ),
      { params: { id: "lex_1", decision: "confirm" } },
    );
    expect(res.status).toBe(401);
    expect(sent).toHaveLength(0);
  });
});

describe("PATCH /api/admin/lexicon/[id]", () => {
  it("forwards only the supplied string fields (D7: omitted means unchanged)", async () => {
    const sent = stubDispatch(rawEntry({ canonical_form: "TOEE TIRE LTD" }));

    const res = await PATCH(
      await request(
        "https://wb.test/api/admin/lexicon/lex_1",
        jsonInit({ canonicalForm: "TOEE TIRE LTD", hitCount: 999 }, "PATCH"),
      ),
      { params: { id: "lex_1" } },
    );

    expect(res.status).toBe(200);
    expect(sent[0]).toMatchObject({
      action: "edit_lexicon_entry",
      params: { id: "lex_1", canonical_form: "TOEE TIRE LTD" },
      actor_account_id: "seed-supervisor",
    });
    // hit_count is D6's rollup column -- a caller cannot smuggle it in.
    expect(sent[0]?.params).not.toHaveProperty("hit_count");
  });

  it("400s on a body that is not JSON", async () => {
    const sent = stubDispatch();
    const res = await PATCH(
      await request(
        "https://wb.test/api/admin/lexicon/lex_1",
        jsonInit("not json", "PATCH"),
      ),
      { params: { id: "lex_1" } },
    );
    expect(res.status).toBe(400);
    expect(sent).toHaveLength(0);
  });

  it("400s -- not 502 -- when the body carries no editable field", async () => {
    // Review finding E: a request the BFF can see is malformed must not travel
    // to Hermes and come back as `unexpected_error` -> 502 "Bad Gateway".
    const sent = stubDispatch();
    const res = await PATCH(
      await request("https://wb.test/api/admin/lexicon/lex_1", jsonInit({}, "PATCH")),
      { params: { id: "lex_1" } },
    );
    expect(res.status).toBe(400);
    expect(sent).toHaveLength(0);
  });
});

describe("GET /api/admin/lexicon", () => {
  it("forwards the queue filters and omits the ones not supplied", async () => {
    const sent = stubDispatch({ entries: [rawEntry()], lexicon_version: null });

    const res = await GET(
      await request("https://wb.test/api/admin/lexicon?status=proposed"),
    );

    expect(res.status).toBe(200);
    expect(sent[0]).toMatchObject({
      action: "list_lexicon_entries",
      params: { status: "proposed" },
    });
    expect(sent[0]?.params).not.toHaveProperty("domain");
  });
});

describe("POST /api/admin/lexicon", () => {
  it("dispatches add_lexicon_entry and returns 201", async () => {
    const sent = stubDispatch(
      rawEntry({
        status: "confirmed",
        provenance: "admin_manual",
        decider_account_id: "seed-supervisor",
        decided_at: "2026-07-21T10:00:00Z",
      }),
    );

    const res = await POST_LEXICON(
      await request(
        "https://wb.test/api/admin/lexicon",
        jsonInit(
          {
            domain: "company",
            entryKind: "alias",
            surfaceForm: "TOEE",
            canonicalForm: "TOEE TIRE",
          },
          "POST",
        ),
      ),
    );

    expect(res.status).toBe(201);
    expect(sent[0]).toMatchObject({
      action: "add_lexicon_entry",
      actor_account_id: "seed-supervisor",
    });
  });

  it.each(["domain", "entryKind", "surfaceForm", "canonicalForm"])(
    "400s -- not 502 -- when %s is blank",
    async (field) => {
      // Review finding E: an empty Domain in the add form used to reach Hermes,
      // come back `unexpected_error`, and render to the admin as 502 Bad Gateway.
      const sent = stubDispatch();
      const res = await POST_LEXICON(
        await request(
          "https://wb.test/api/admin/lexicon",
          jsonInit(
            {
              domain: "company",
              entryKind: "alias",
              surfaceForm: "TOEE",
              canonicalForm: "TOEE TIRE",
              [field]: "   ",
            },
            "POST",
          ),
        ),
      );

      expect(res.status).toBe(400);
      expect(await res.json()).toMatchObject({ error: expect.stringContaining(field) });
      expect(sent).toHaveLength(0);
    },
  );

  it("400s on a missing body", async () => {
    const sent = stubDispatch();
    const res = await POST_LEXICON(
      await request("https://wb.test/api/admin/lexicon", { method: "POST" }),
    );
    expect(res.status).toBe(400);
    expect(sent).toHaveLength(0);
  });
});
