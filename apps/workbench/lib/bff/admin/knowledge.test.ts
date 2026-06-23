import { beforeEach, describe, expect, it } from "vitest";
import { WORKBENCH_ROLES } from "@toee/shared";
import { createInMemoryAccountStore } from "../../auth/account-store";
import type { WorkbenchSession } from "../../auth/session";
import { createInMemoryEvalStore } from "../../gateway/eval-store";
import {
  createInMemoryKnowledgeStore,
  type KnowledgeStore,
  type PolicySlot,
} from "../../gateway/knowledge-store";
import type { AdminDeps } from "./deps";
import {
  handleListSlots,
  handleRollbackSlot,
  handleSaveDraft,
  handleSubmitSlot,
} from "./knowledge";

const NOW = 1_700_000_000_000;

// Eval + account stores are never read or mutated by the knowledge handlers, so
// build them once (the account store seeds via scrypt, which is slow).
const evalStore = createInMemoryEvalStore([]);
const accounts = createInMemoryAccountStore(0);

let knowledge: KnowledgeStore;

beforeEach(() => {
  knowledge = createInMemoryKnowledgeStore();
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

function putReq(body: unknown): Request {
  return new Request("http://localhost/api/admin/knowledge/slots/x", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleListSlots", () => {
  it("returns every required policy slot", async () => {
    const res = handleListSlots(deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slots: PolicySlot[] };
    expect(body.slots).toHaveLength(6);
    expect(body.slots.map((s) => s.slotId)).toContain("business-hours");
  });
});

describe("handleSaveDraft", () => {
  it("saves draft text and flips an empty slot to draft", async () => {
    const res = await handleSaveDraft(
      putReq({ draftText: "Returns accepted within 30 days." }),
      "returns-exchanges",
      deps(),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slot: PolicySlot };
    expect(body.slot.draftText).toBe("Returns accepted within 30 days.");
    expect(body.slot.status).toBe("draft");
  });

  it("404s an unknown slot", async () => {
    const res = await handleSaveDraft(
      putReq({ draftText: "anything" }),
      "ghost-slot",
      deps(),
    );
    expect(res.status).toBe(404);
  });
});

describe("handleSubmitSlot", () => {
  it("submits a draft slot for eval", async () => {
    const res = handleSubmitSlot("order-delivery", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slot: PolicySlot };
    expect(body.slot.status).toBe("pending_eval");
  });

  it("409s when the slot has no draft", async () => {
    const res = handleSubmitSlot("returns-exchanges", deps());
    expect(res.status).toBe(409);
    expect((await res.json()) as { error: string }).toEqual({
      error: "slot has no draft to submit",
    });
  });

  it("404s an unknown slot", () => {
    expect(handleSubmitSlot("ghost-slot", deps()).status).toBe(404);
  });
});

describe("handleRollbackSlot", () => {
  it("rolls a published slot back to its previous version", async () => {
    const res = handleRollbackSlot("business-hours", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { slot: PolicySlot };
    expect(body.slot.status).toBe("published");
    expect(body.slot.publishedText).toBe("Open Mon–Fri 9am–5pm.");
  });

  it("409s when there is no previous published version", async () => {
    const res = handleRollbackSlot("payment-methods", deps());
    expect(res.status).toBe(409);
  });

  it("404s an unknown slot", () => {
    expect(handleRollbackSlot("ghost-slot", deps()).status).toBe(404);
  });
});
