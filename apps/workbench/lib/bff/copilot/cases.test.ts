import { beforeEach, describe, expect, it } from "vitest";
import { createDefaultMockDriver, type ToolDriver } from "@toee/domain-adapters";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import type { WorkbenchSession } from "../../auth/session";
import { createInMemoryGatewayStore, type GatewayStore } from "../../gateway/store";
import { createSeed } from "../../gateway/seed";
import type { AuditAction, WorkbenchCase } from "../../gateway/types";
import type { CopilotDeps } from "./deps";
import {
  handleAssign,
  handleClaim,
  handleContactReason,
  handleGetAuditLog,
  handleGetCase,
  handleGetThread,
  handleListCases,
  handlePriority,
  handleResolve,
} from "./cases";

const NOW = 1_700_000_000_000;

let store: GatewayStore;
let driver: ToolDriver;

beforeEach(() => {
  store = createInMemoryGatewayStore(createSeed());
  driver = createDefaultMockDriver();
});

function session(
  role: WorkbenchRoleId = WORKBENCH_ROLES.rep,
  accountId = "seed-rep",
  username = "rep",
): WorkbenchSession {
  return { accountId, username, role, lastActivityAt: NOW };
}

function deps(s: WorkbenchSession = session()): CopilotDeps {
  return { store, driver, session: s, now: NOW };
}

function listReq(query = ""): Request {
  return new Request(`http://localhost/api/copilot/cases${query}`);
}

function jsonReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/cases/x", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function actions(caseId: string): AuditAction[] {
  return store.getCaseAuditLog(caseId).map((e) => e.action);
}

describe("handleListCases", () => {
  it("defaults a rep to mine_or_unassigned over open/in_progress", async () => {
    const res = handleListCases(listReq(), deps());
    expect(res.status).toBe(200);
    const ids = ((await res.json()) as { cases: WorkbenchCase[] }).cases.map(
      (c) => c.caseId,
    );
    // unassigned open cases + the rep's own in_progress case; resolved + sales hidden.
    expect(ids).toContain("case_ar_urgent");
    expect(ids).toContain("case_billing_email");
    expect(ids).not.toContain("case_resolved");
    expect(ids).not.toContain("case_sales");
    expect(ids[0]).toBe("case_ar_urgent"); // urgent sorts first
  });

  it("hides another account's case from a rep but shows it to a supervisor", async () => {
    store.assignCase("case_unmatched", "seed-supervisor");

    const repIds = (
      (await handleListCases(listReq(), deps()).json()) as {
        cases: WorkbenchCase[];
      }
    ).cases.map((c) => c.caseId);
    expect(repIds).not.toContain("case_unmatched");

    const supIds = (
      (await handleListCases(
        listReq(),
        deps(session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor")),
      ).json()) as { cases: WorkbenchCase[] }
    ).cases.map((c) => c.caseId);
    expect(supIds).toContain("case_unmatched");
  });

  it("honours assignee=mine", async () => {
    const ids = (
      (await handleListCases(listReq("?assignee=mine"), deps()).json()) as {
        cases: WorkbenchCase[];
      }
    ).cases.map((c) => c.caseId);
    expect(ids).toEqual(["case_billing_email"]);
  });

  it("parses an explicit status filter (csv)", async () => {
    const ids = (
      (await handleListCases(
        listReq("?assignee=mine&status=resolved"),
        deps(),
      ).json()) as { cases: WorkbenchCase[] }
    ).cases.map((c) => c.caseId);
    expect(ids).toEqual(["case_resolved"]);
  });
});

describe("handleGetCase", () => {
  it("returns the case", async () => {
    const res = handleGetCase("case_ar_urgent", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.caseId).toBe("case_ar_urgent");
  });

  it("404s an unknown case", () => {
    expect(handleGetCase("nope", deps()).status).toBe(404);
  });
});

describe("handleGetThread", () => {
  it("returns case + sorted messages and writes a case_view audit", async () => {
    const res = handleGetThread("case_ar_urgent", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      case: WorkbenchCase;
      messages: { at: number }[];
    };
    expect(body.case.caseId).toBe("case_ar_urgent");
    expect(body.messages.length).toBeGreaterThan(0);
    const ats = body.messages.map((m) => m.at);
    expect([...ats].sort((a, b) => a - b)).toEqual(ats);
    expect(actions("case_ar_urgent")).toContain("case_view");
  });

  it("404s an unknown case without writing audit", () => {
    expect(handleGetThread("nope", deps()).status).toBe(404);
    expect(actions("nope")).toEqual([]);
  });
});

describe("handleGetAuditLog", () => {
  it("returns the case audit entries", async () => {
    const res = handleGetAuditLog("case_billing_email", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { entries: { action: string }[] };
    expect(body.entries.length).toBeGreaterThanOrEqual(2);
  });

  it("404s an unknown case", () => {
    expect(handleGetAuditLog("nope", deps()).status).toBe(404);
  });
});

describe("handleClaim", () => {
  it("claims an unassigned case and writes an audit", async () => {
    const res = handleClaim("case_ar_urgent", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.assigneeAccountId).toBe("seed-rep");
    expect(body.case.status).toBe("in_progress");
    expect(actions("case_ar_urgent")).toContain("claim_case");
  });

  it("is idempotent when the actor already holds the case", () => {
    expect(handleClaim("case_billing_email", deps()).status).toBe(200);
  });

  it("409s when another account holds the case", () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    expect(handleClaim("case_billing_email", deps(sup)).status).toBe(409);
  });

  it("404s an unknown case", () => {
    expect(handleClaim("nope", deps()).status).toBe(404);
  });
});

describe("handleAssign (supervisor/admin only)", () => {
  it("403s a rep", async () => {
    const res = await handleAssign(
      jsonReq({ assigneeAccountId: "seed-rep" }),
      "case_ar_urgent",
      deps(),
    );
    expect(res.status).toBe(403);
  });

  it("assigns as a supervisor and writes an audit", async () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    const res = await handleAssign(
      jsonReq({ assigneeAccountId: "seed-rep" }),
      "case_ar_urgent",
      deps(sup),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.assigneeAccountId).toBe("seed-rep");
    expect(actions("case_ar_urgent")).toContain("assign_case");
  });

  it("400s a missing assigneeAccountId", async () => {
    const admin = session(WORKBENCH_ROLES.admin, "seed-admin", "admin");
    const res = await handleAssign(jsonReq({}), "case_ar_urgent", deps(admin));
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    const res = await handleAssign(
      jsonReq({ assigneeAccountId: "seed-rep" }),
      "nope",
      deps(sup),
    );
    expect(res.status).toBe(404);
  });
});

describe("handleResolve", () => {
  it("resolves a case for any authorized user and writes an audit", async () => {
    const res = handleResolve("case_ar_urgent", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.status).toBe("resolved");
    expect(body.case.resolvedByAccountId).toBe("seed-rep");
    expect(actions("case_ar_urgent")).toContain("resolve_case");
  });

  it("404s an unknown case", () => {
    expect(handleResolve("nope", deps()).status).toBe(404);
  });
});

describe("handlePriority (supervisor/admin only)", () => {
  it("403s a rep", async () => {
    const res = await handlePriority(jsonReq({ urgent: false }), "case_ar_urgent", deps());
    expect(res.status).toBe(403);
  });

  it("updates priority as a supervisor and writes an audit", async () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    const res = await handlePriority(
      jsonReq({ urgent: false }),
      "case_ar_urgent",
      deps(sup),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.urgent).toBe(false);
    expect(actions("case_ar_urgent")).toContain("update_priority");
  });

  it("400s a non-boolean urgent", async () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    const res = await handlePriority(
      jsonReq({ urgent: "yes" }),
      "case_ar_urgent",
      deps(sup),
    );
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    const res = await handlePriority(jsonReq({ urgent: true }), "nope", deps(sup));
    expect(res.status).toBe(404);
  });
});

describe("handleContactReason", () => {
  it("updates the contact reason and writes an audit", async () => {
    const res = await handleContactReason(
      jsonReq({ contactReason: "warranty" }),
      "case_ar_urgent",
      deps(),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.contactReason).toBe("warranty");
    expect(actions("case_ar_urgent")).toContain("update_contact_reason");
  });

  it("400s an empty contact reason", async () => {
    const res = await handleContactReason(
      jsonReq({ contactReason: "  " }),
      "case_ar_urgent",
      deps(),
    );
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const res = await handleContactReason(
      jsonReq({ contactReason: "warranty" }),
      "nope",
      deps(),
    );
    expect(res.status).toBe(404);
  });
});
