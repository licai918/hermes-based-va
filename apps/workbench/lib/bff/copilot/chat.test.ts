import { beforeEach, describe, expect, it } from "vitest";
import { createDefaultMockDriver, type ToolDriver } from "@toee/domain-adapters";
import { WORKBENCH_ROLES } from "@toee/shared";
import type { WorkbenchSession } from "../../auth/session";
import { createInMemoryGatewayStore, type GatewayStore } from "../../gateway/store";
import { createSeed } from "../../gateway/seed";
import type { CopilotDeps } from "./deps";
import { handleChat } from "./chat";

const NOW = 1_800_000_000_000;

let store: GatewayStore;
let driver: ToolDriver;

beforeEach(() => {
  store = createInMemoryGatewayStore(createSeed());
  driver = createDefaultMockDriver();
});

function deps(): CopilotDeps {
  return {
    store,
    driver,
    session: {
      accountId: "seed-rep",
      username: "rep",
      role: WORKBENCH_ROLES.rep,
      lastActivityAt: NOW,
    },
    now: NOW,
  };
}

function chatReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

type ChatResponse = {
  state: string;
  reply: string;
  draftCard?: { channel: string; body: string };
};

describe("handleChat", () => {
  it("400s an empty message", async () => {
    const res = await handleChat(chatReq({ message: "   " }), deps());
    expect(res.status).toBe(400);
  });

  it("returns needs_case when no case is selected", async () => {
    const res = await handleChat(chatReq({ message: "help me" }), deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as ChatResponse;
    expect(body.state).toBe("needs_case");
    expect(body.reply).toMatch(/select/i);
    expect(body.draftCard).toBeUndefined();
  });

  it("404s when the selected case is missing", async () => {
    const res = await handleChat(
      chatReq({ caseId: "nope", message: "hi" }),
      deps(),
    );
    expect(res.status).toBe(404);
  });

  it("returns a ready reply referencing the case for a plain message", async () => {
    const res = await handleChat(
      chatReq({ caseId: "case_ar_urgent", message: "what's going on here?" }),
      deps(),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as ChatResponse;
    expect(body.state).toBe("ready");
    expect(body.reply).toContain("order_status"); // contactReason of case_ar_urgent
    expect(body.draftCard).toBeUndefined();
  });

  it("attaches an SMS draftCard when asked to draft on an SMS case", async () => {
    const res = await handleChat(
      chatReq({ caseId: "case_ar_urgent", message: "please draft a reply" }),
      deps(),
    );
    const body = (await res.json()) as ChatResponse;
    expect(body.state).toBe("ready");
    expect(body.draftCard?.channel).toBe("sms");
    expect(typeof body.draftCard?.body).toBe("string");
    expect(body.draftCard?.body.length).toBeGreaterThan(0);
  });

  it("does not attach a draftCard on a non-SMS case", async () => {
    const res = await handleChat(
      chatReq({ caseId: "case_billing_email", message: "draft an sms please" }),
      deps(),
    );
    const body = (await res.json()) as ChatResponse;
    expect(body.state).toBe("ready");
    expect(body.draftCard).toBeUndefined();
  });
});
