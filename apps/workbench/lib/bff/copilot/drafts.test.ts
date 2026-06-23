import { beforeEach, describe, expect, it } from "vitest";
import {
  createDefaultMockDriver,
  createMockDriver,
  type ToolDriver,
} from "@toee/domain-adapters";
import { WORKBENCH_ROLES } from "@toee/shared";
import type { WorkbenchSession } from "../../auth/session";
import { createInMemoryGatewayStore, type GatewayStore } from "../../gateway/store";
import { createSeed } from "../../gateway/seed";
import type { AuditAction } from "../../gateway/types";
import type { CopilotDeps } from "./deps";
import { handleDraft } from "./drafts";

const NOW = 1_700_000_000_000;

let store: GatewayStore;
let driver: ToolDriver;

beforeEach(() => {
  store = createInMemoryGatewayStore(createSeed());
  driver = createDefaultMockDriver();
});

function session(): WorkbenchSession {
  return {
    accountId: "seed-rep",
    username: "rep",
    role: WORKBENCH_ROLES.rep,
    lastActivityAt: NOW,
  };
}

function deps(override?: Partial<CopilotDeps>): CopilotDeps {
  return { store, driver, session: session(), now: NOW, ...override };
}

function draftReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/drafts/sms", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function actions(caseId: string): AuditAction[] {
  return store.getCaseAuditLog(caseId).map((e) => e.action);
}

describe("handleDraft", () => {
  it("drafts an SMS and writes a draft_generated audit", async () => {
    const res = await handleDraft(
      draftReq({ caseId: "case_ar_urgent", prompt: "reassure them" }),
      deps(),
      "draft_sms",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { draft: { channel: string; draft: string } };
    expect(body.draft.channel).toBe("sms");
    expect(typeof body.draft.draft).toBe("string");
    const entry = store
      .getCaseAuditLog("case_ar_urgent")
      .find((e) => e.action === "draft_generated");
    expect(entry?.detail).toBe("draft_sms");
  });

  it("drafts an email with the draft_email detail", async () => {
    const res = await handleDraft(
      draftReq({ caseId: "case_billing_email" }),
      deps(),
      "draft_email",
    );
    expect(res.status).toBe(200);
    const entry = store
      .getCaseAuditLog("case_billing_email")
      .find((e) => e.action === "draft_generated" && e.detail === "draft_email");
    expect(entry).toBeDefined();
  });

  it("drafts an internal note with the draft_internal_note detail", async () => {
    const res = await handleDraft(
      draftReq({ caseId: "case_ar_urgent" }),
      deps(),
      "draft_internal_note",
    );
    expect(res.status).toBe(200);
    expect(actions("case_ar_urgent")).toContain("draft_generated");
  });

  it("400s a missing caseId", async () => {
    const res = await handleDraft(draftReq({ prompt: "hi" }), deps(), "draft_sms");
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const res = await handleDraft(draftReq({ caseId: "nope" }), deps(), "draft_sms");
    expect(res.status).toBe(404);
  });

  it("502s on tool failure without writing an audit", async () => {
    const res = await handleDraft(
      draftReq({ caseId: "case_ar_urgent" }),
      deps({ driver: createMockDriver({}) }),
      "draft_sms",
    );
    expect(res.status).toBe(502);
    expect(actions("case_ar_urgent")).not.toContain("draft_generated");
  });
});
