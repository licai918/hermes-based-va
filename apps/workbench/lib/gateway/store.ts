// In-memory Workbench GatewayStore — the Slice-2 source of truth for cases,
// threads, the Workbench Audit Log, sales-outreach, and auto-handled records.
// STUB SEAM: Slice 3 replaces createInMemoryGatewayStore with a Postgres-backed
// implementation behind this same interface. Pure data + deterministic ordering;
// audit entries are appended by the BFF handlers (which know the acting account).
import { createSeed } from "./seed";
import type {
  AuditLogEntry,
  AutoHandledRecord,
  CaseListFilter,
  CaseStatus,
  ThreadMessage,
  WorkbenchCase,
} from "./types";

export interface GatewayStore {
  listCases(filter: CaseListFilter): WorkbenchCase[];
  getCase(caseId: string): WorkbenchCase | undefined;
  getThread(caseId: string): ThreadMessage[];
  appendThreadMessage(caseId: string, message: ThreadMessage): void;
  getCaseAuditLog(caseId: string): AuditLogEntry[];
  appendAuditEntry(entry: AuditLogEntry): void;
  claimCase(caseId: string, accountId: string): WorkbenchCase | undefined;
  assignCase(caseId: string, assigneeAccountId: string): WorkbenchCase | undefined;
  resolveCase(caseId: string, accountId: string): WorkbenchCase | undefined;
  updatePriority(caseId: string, urgent: boolean): WorkbenchCase | undefined;
  updateContactReason(caseId: string, contactReason: string): WorkbenchCase | undefined;
  listSalesOutreach(): WorkbenchCase[];
  getSalesOutreach(caseId: string): WorkbenchCase | undefined;
  listAutoHandled(): AutoHandledRecord[];
  getAutoHandled(recordId: string): AutoHandledRecord | undefined;
}

export interface GatewayStoreSeed {
  cases: WorkbenchCase[];
  threads?: Record<string, ThreadMessage[]>;
  auditLog?: AuditLogEntry[];
  autoHandled?: AutoHandledRecord[];
}

const DEFAULT_STATUSES: CaseStatus[] = ["open", "in_progress"];

const SALES_OUTREACH = "sales_outreach";

// ADR-0079 default queue sort: urgent first, unassigned before assigned, oldest
// open first within a tier.
function queueCompare(a: WorkbenchCase, b: WorkbenchCase): number {
  if (a.urgent !== b.urgent) return a.urgent ? -1 : 1;
  const aAssigned = a.assigneeAccountId === null ? 0 : 1;
  const bAssigned = b.assigneeAccountId === null ? 0 : 1;
  if (aAssigned !== bAssigned) return aAssigned - bAssigned;
  return a.openedAt - b.openedAt;
}

export function createInMemoryGatewayStore(seed: GatewayStoreSeed): GatewayStore {
  const casesById = new Map<string, WorkbenchCase>();
  for (const c of seed.cases) casesById.set(c.caseId, c);

  const threadsById = new Map<string, ThreadMessage[]>();
  for (const [threadId, messages] of Object.entries(seed.threads ?? {})) {
    threadsById.set(threadId, [...messages]);
  }

  const auditLog: AuditLogEntry[] = [...(seed.auditLog ?? [])];

  const autoHandledById = new Map<string, AutoHandledRecord>();
  for (const record of seed.autoHandled ?? []) {
    autoHandledById.set(record.recordId, record);
  }

  function matchesAssignee(c: WorkbenchCase, filter: CaseListFilter): boolean {
    const assignee = filter.assignee;
    if (!assignee || assignee.mode === "all") return true;
    switch (assignee.mode) {
      case "mine":
        return c.assigneeAccountId === assignee.accountId;
      case "unassigned":
        return c.assigneeAccountId === null;
      case "mine_or_unassigned":
        return (
          c.assigneeAccountId === null ||
          c.assigneeAccountId === assignee.accountId
        );
    }
  }

  return {
    listCases(filter) {
      const statuses = filter.statuses ?? DEFAULT_STATUSES;
      return [...casesById.values()]
        .filter((c) => c.contactReason !== SALES_OUTREACH)
        .filter((c) => statuses.includes(c.status))
        .filter((c) => matchesAssignee(c, filter))
        .sort(queueCompare);
    },
    getCase(caseId) {
      return casesById.get(caseId);
    },
    getThread(caseId) {
      const found = casesById.get(caseId);
      if (!found) return [];
      const messages = threadsById.get(found.threadId) ?? [];
      return [...messages].sort((a, b) => a.at - b.at);
    },
    appendThreadMessage(caseId, message) {
      const found = casesById.get(caseId);
      if (!found) return;
      const messages = threadsById.get(found.threadId) ?? [];
      messages.push(message);
      threadsById.set(found.threadId, messages);
      found.lastActivityAt = Math.max(found.lastActivityAt, message.at);
    },
    getCaseAuditLog(caseId) {
      return auditLog
        .filter((entry) => entry.caseId === caseId)
        .sort((a, b) => a.at - b.at);
    },
    appendAuditEntry(entry) {
      auditLog.push(entry);
    },
    claimCase(caseId, accountId) {
      const found = casesById.get(caseId);
      if (!found) return undefined;
      found.assigneeAccountId = accountId;
      if (found.status === "open") found.status = "in_progress";
      return found;
    },
    assignCase(caseId, assigneeAccountId) {
      const found = casesById.get(caseId);
      if (!found) return undefined;
      found.assigneeAccountId = assigneeAccountId;
      if (found.status === "open") found.status = "in_progress";
      return found;
    },
    resolveCase(caseId, accountId) {
      const found = casesById.get(caseId);
      if (!found) return undefined;
      found.status = "resolved";
      found.resolvedByAccountId = accountId;
      return found;
    },
    updatePriority(caseId, urgent) {
      const found = casesById.get(caseId);
      if (!found) return undefined;
      found.urgent = urgent;
      return found;
    },
    updateContactReason(caseId, contactReason) {
      const found = casesById.get(caseId);
      if (!found) return undefined;
      found.contactReason = contactReason;
      return found;
    },
    listSalesOutreach() {
      return [...casesById.values()]
        .filter((c) => c.contactReason === SALES_OUTREACH)
        .sort((a, b) => b.lastActivityAt - a.lastActivityAt);
    },
    getSalesOutreach(caseId) {
      const found = casesById.get(caseId);
      return found && found.contactReason === SALES_OUTREACH ? found : undefined;
    },
    listAutoHandled() {
      return [...autoHandledById.values()].sort(
        (a, b) => b.lastActivityAt - a.lastActivityAt,
      );
    },
    getAutoHandled(recordId) {
      return autoHandledById.get(recordId);
    },
  };
}

// Process-wide singleton used by the copilot BFF so claims/assignments/audit
// persist across requests in dev. Tests build their own store via
// createInMemoryGatewayStore instead of touching this.
let singleton: GatewayStore | undefined;

export function getGatewayStore(): GatewayStore {
  if (!singleton) singleton = createInMemoryGatewayStore(createSeed());
  return singleton;
}
