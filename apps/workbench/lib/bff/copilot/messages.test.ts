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
import { handleTextlineSend } from "./messages";

// After the seed's anchored timestamps (June 2026) so an appended reply sorts
// last in the thread, matching real wall-clock sends.
const NOW = 1_800_000_000_000;

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

function sendReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/messages/textline/send", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function actions(caseId: string): AuditAction[] {
  return store.getCaseAuditLog(caseId).map((e) => e.action);
}

describe("handleTextlineSend", () => {
  it("sends on an eligible (claimed, active SMS) case: appends thread + audit", async () => {
    store.claimCase("case_ar_urgent", "seed-rep");
    const before = store.getThread("case_ar_urgent").length;

    const res = await handleTextlineSend(
      sendReq({ caseId: "case_ar_urgent", body: "Your tires arrive today." }),
      deps(),
    );
    expect(res.status).toBe(200);
    const payload = (await res.json()) as { message: { messageId: string } };
    expect(payload.message.messageId).toBeTruthy();

    const thread = store.getThread("case_ar_urgent");
    expect(thread.length).toBe(before + 1);
    const last = thread[thread.length - 1]!;
    expect(last.author).toBe("workbench");
    expect(last.body).toBe("Your tires arrive today.");
    expect(actions("case_ar_urgent")).toContain("textline_send");
  });

  it("400s an empty body before any case lookup", async () => {
    const res = await handleTextlineSend(
      sendReq({ caseId: "case_ar_urgent", body: "  " }),
      deps(),
    );
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const res = await handleTextlineSend(
      sendReq({ caseId: "nope", body: "hello" }),
      deps(),
    );
    expect(res.status).toBe(404);
  });

  it("403s when the case is not claimed by the acting account", async () => {
    const res = await handleTextlineSend(
      sendReq({ caseId: "case_ar_urgent", body: "hello" }),
      deps(),
    );
    expect(res.status).toBe(403);
  });

  it("403s a non-SMS case even when assigned to the actor", async () => {
    const res = await handleTextlineSend(
      sendReq({ caseId: "case_billing_email", body: "hello" }),
      deps(),
    );
    expect(res.status).toBe(403);
  });

  it("403s an SMS case with no active SMS session", async () => {
    // case_resolved is sms + assigned seed-rep but smsSessionActive is false.
    const res = await handleTextlineSend(
      sendReq({ caseId: "case_resolved", body: "hello" }),
      deps(),
    );
    expect(res.status).toBe(403);
  });

  it("502s on tool failure without fabricating a thread message or audit", async () => {
    store.claimCase("case_ar_urgent", "seed-rep");
    const before = store.getThread("case_ar_urgent").length;

    const res = await handleTextlineSend(
      sendReq({ caseId: "case_ar_urgent", body: "hello" }),
      deps({ driver: createMockDriver({}) }),
    );
    expect(res.status).toBe(502);
    expect(store.getThread("case_ar_urgent").length).toBe(before);
    expect(actions("case_ar_urgent")).not.toContain("textline_send");
  });
});
