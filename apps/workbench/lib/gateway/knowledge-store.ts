// In-memory KnowledgeOps store for the six Required Operational Policy Slots
// (ADR-0003) backing /admin/knowledge (ADR-0087). STUB SEAM: Slice 3+ replaces
// this with persisted policy knowledge + the real Knowledge Publish Eval Gate
// (ADR-0040). Deterministic seed so the master-detail UI renders every status.

export type SlotStatus = "empty" | "draft" | "pending_eval" | "published" | "gap";

export interface PolicySlot {
  slotId: string;
  title: string;
  status: SlotStatus;
  draftText: string | null;
  publishedText: string | null;
  owner: string | null;
  reviewDate: string | null;
  hasGapPrompt: boolean;
}

// Stable slot identifiers + titles, in ADR-0003 order. The list pane renders
// these as fixed entries.
export const REQUIRED_SLOTS: ReadonlyArray<{ slotId: string; title: string }> = [
  { slotId: "business-hours", title: "Business hours and service boundaries" },
  { slotId: "payment-methods", title: "Payment methods and Payment Link rules" },
  { slotId: "order-delivery", title: "Order and delivery inquiry guidance" },
  { slotId: "accounting-inquiry", title: "Accounting inquiry guidance" },
  { slotId: "returns-exchanges", title: "Returns, exchanges, and stockout policy" },
  { slotId: "exception-scripts", title: "Standard exception scripts" },
];

export const REQUIRED_SLOT_IDS = REQUIRED_SLOTS.map((s) => s.slotId);

export type SubmitResult =
  | { ok: true; slot: PolicySlot }
  | { ok: false; reason: "not_found" | "no_draft" };

export type RollbackResult =
  | { ok: true; slot: PolicySlot }
  | { ok: false; reason: "not_found" | "no_previous_version" };

export interface KnowledgeStore {
  listSlots(): PolicySlot[];
  getSlot(slotId: string): PolicySlot | undefined;
  saveDraft(
    slotId: string,
    patch: { draftText?: string; owner?: string; reviewDate?: string },
  ): PolicySlot | undefined;
  submitForEval(slotId: string): SubmitResult;
  rollbackPublished(slotId: string): RollbackResult;
}

interface SlotState extends PolicySlot {
  // Prior published versions, most recent last. Rollback restores the previous.
  publishedHistory: string[];
}

function seedSlots(): SlotState[] {
  const base = (slotId: string): SlotState => {
    const meta = REQUIRED_SLOTS.find((s) => s.slotId === slotId)!;
    return {
      slotId,
      title: meta.title,
      status: "empty",
      draftText: null,
      publishedText: null,
      owner: null,
      reviewDate: null,
      hasGapPrompt: false,
      publishedHistory: [],
    };
  };
  const businessHours = base("business-hours");
  businessHours.status = "published";
  businessHours.publishedText = "Open Mon–Fri 8am–6pm; after-hours messages handled next business day.";
  businessHours.publishedHistory = ["Open Mon–Fri 9am–5pm."];
  businessHours.owner = "ops-lead";
  businessHours.reviewDate = "2026-09-01";

  const paymentMethods = base("payment-methods");
  paymentMethods.status = "published";
  paymentMethods.publishedText = "Card and approved net terms; Payment Links only to verified destinations.";
  paymentMethods.owner = "ops-lead";

  const orderDelivery = base("order-delivery");
  orderDelivery.status = "draft";
  orderDelivery.draftText = "Confirm order number, then share ship/delivery status.";

  const accounting = base("accounting-inquiry");
  accounting.status = "pending_eval";
  accounting.draftText = "Check email-link status before quoting AR balances.";

  const returns = base("returns-exchanges");

  const exceptions = base("exception-scripts");
  exceptions.status = "gap";
  exceptions.hasGapPrompt = true;

  return [businessHours, paymentMethods, orderDelivery, accounting, returns, exceptions];
}

function toPublic(state: SlotState): PolicySlot {
  const { publishedHistory, ...rest } = state;
  void publishedHistory;
  return { ...rest };
}

export function createInMemoryKnowledgeStore(): KnowledgeStore {
  const byId = new Map<string, SlotState>();
  for (const slot of seedSlots()) byId.set(slot.slotId, slot);

  return {
    listSlots() {
      return REQUIRED_SLOT_IDS.map((id) => toPublic(byId.get(id)!));
    },
    getSlot(slotId) {
      const found = byId.get(slotId);
      return found ? toPublic(found) : undefined;
    },
    saveDraft(slotId, patch) {
      const found = byId.get(slotId);
      if (!found) return undefined;
      if (patch.draftText !== undefined) found.draftText = patch.draftText;
      if (patch.owner !== undefined) found.owner = patch.owner;
      if (patch.reviewDate !== undefined) found.reviewDate = patch.reviewDate;
      if (
        found.draftText !== null &&
        found.draftText.length > 0 &&
        (found.status === "empty" || found.status === "gap")
      ) {
        found.status = "draft";
      }
      return toPublic(found);
    },
    submitForEval(slotId) {
      const found = byId.get(slotId);
      if (!found) return { ok: false, reason: "not_found" };
      if (found.draftText === null || found.draftText.length === 0) {
        return { ok: false, reason: "no_draft" };
      }
      found.status = "pending_eval";
      return { ok: true, slot: toPublic(found) };
    },
    rollbackPublished(slotId) {
      const found = byId.get(slotId);
      if (!found) return { ok: false, reason: "not_found" };
      const previous = found.publishedHistory.pop();
      if (previous === undefined) {
        return { ok: false, reason: "no_previous_version" };
      }
      found.publishedText = previous;
      found.status = "published";
      return { ok: true, slot: toPublic(found) };
    },
  };
}

let singleton: KnowledgeStore | undefined;

export function getKnowledgeStore(): KnowledgeStore {
  if (!singleton) singleton = createInMemoryKnowledgeStore();
  return singleton;
}
