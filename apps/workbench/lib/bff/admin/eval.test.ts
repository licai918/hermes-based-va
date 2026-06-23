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
import { createInMemoryKnowledgeStore } from "../../gateway/knowledge-store";
import type { AdminDeps } from "./deps";
import {
  handleGetRun,
  handleListRuns,
  handlePromote,
  handleSignOff,
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
