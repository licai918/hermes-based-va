// Typed browser-side wrappers for the Admin Governance Console BFF endpoints
// (ADR-0087 knowledge, ADR-0088 eval, ADR-0089 accounts). Thin over getJson/
// sendJson so non-2xx responses raise the shared ApiError — except createAccount,
// whose 400 carries a policy `errors[]` we surface inline rather than throw.
import type { WorkbenchRoleId } from "@toee/shared";
import type { PublicAccount } from "@/lib/bff/admin/accounts";
import type { CorpusStatus, ProbeResult, ReingestQueued } from "@/lib/bff/admin/knowledge";
import type { AggregateMetrics } from "@/lib/bff/admin/metrics";
import type { RetentionStatus, RetentionSweepQueued } from "@/lib/bff/admin/retention";
import type { EvalRunReport, EvalRunSummary } from "@/lib/gateway/eval-store";
import type { PolicySlot } from "@/lib/gateway/knowledge-store";
import type {
  AgentExperienceEntry,
  MemoryAuditView,
  MemoryPreferenceSlot,
} from "@/lib/gateway/types";
import { getJson, sendJson } from "./http";

// --- Knowledge (Required Operational Policy Slots) ---------------------------

export function listSlots(): Promise<PolicySlot[]> {
  return getJson<{ slots: PolicySlot[] }>("/api/admin/knowledge/slots").then(
    (b) => b.slots,
  );
}

export type SlotDraftPatch = {
  draftText?: string;
  owner?: string;
  reviewDate?: string;
};

export function saveDraft(slotId: string, patch: SlotDraftPatch): Promise<PolicySlot> {
  return sendJson<{ slot: PolicySlot }>(
    "PUT",
    `/api/admin/knowledge/slots/${slotId}`,
    patch,
  ).then((b) => b.slot);
}

export function submitSlot(slotId: string): Promise<PolicySlot> {
  return sendJson<{ slot: PolicySlot }>(
    "POST",
    `/api/admin/knowledge/slots/${slotId}/submit`,
  ).then((b) => b.slot);
}

export function rollbackSlot(slotId: string): Promise<PolicySlot> {
  return sendJson<{ slot: PolicySlot }>(
    "POST",
    `/api/admin/knowledge/slots/${slotId}/rollback`,
  ).then((b) => b.slot);
}

// --- S11: corpus status + retrieval probe (FR-6) ------------------------------

export function getCorpusStatus(): Promise<CorpusStatus> {
  return getJson<{ status: CorpusStatus }>("/api/admin/knowledge/corpus-status").then(
    (b) => b.status,
  );
}

// S04 (FR-11): queue a corpus re-ingest for the background worker.
export function triggerCorpusReingest(): Promise<ReingestQueued> {
  return sendJson<ReingestQueued>("POST", "/api/admin/knowledge/reingest");
}

export function probeKnowledge(query: string): Promise<ProbeResult[]> {
  return sendJson<{ results: ProbeResult[] }>("POST", "/api/admin/knowledge/probe", {
    query,
  }).then((b) => b.results);
}

// --- Eval review (Knowledge Publish Eval Gate) -------------------------------

export function listRuns(): Promise<EvalRunSummary[]> {
  return getJson<{ runs: EvalRunSummary[] }>("/api/admin/eval/runs").then(
    (b) => b.runs,
  );
}

export function getRun(runId: string): Promise<EvalRunReport> {
  return getJson<{ run: EvalRunReport }>(`/api/admin/eval/runs/${runId}`).then(
    (b) => b.run,
  );
}

export function signOff(runId: string): Promise<EvalRunReport> {
  return sendJson<{ run: EvalRunReport }>(
    "POST",
    `/api/admin/eval/runs/${runId}/sign-off`,
  ).then((b) => b.run);
}

export function promote(runId: string): Promise<EvalRunReport> {
  return sendJson<{ run: EvalRunReport }>(
    "POST",
    `/api/admin/eval/runs/${runId}/promote`,
  ).then((b) => b.run);
}

// --- Accounts ----------------------------------------------------------------

export function listAccounts(): Promise<PublicAccount[]> {
  return getJson<{ accounts: PublicAccount[] }>("/api/admin/accounts").then(
    (b) => b.accounts,
  );
}

export type CreateAccountInput = {
  username: string;
  role: WorkbenchRoleId;
  password: string;
};

// The create path is the one endpoint whose error body is actionable in the UI:
// a 400 carries the password-policy `errors[]` (ADR-0018) and a 409 means the
// username is taken. Return a result union instead of throwing so the form can
// render those inline rather than only via the global banner.
export type CreateAccountResult =
  | { ok: true; account: PublicAccount }
  | { ok: false; status: number; error: string; errors?: string[] };

export async function createAccount(
  input: CreateAccountInput,
): Promise<CreateAccountResult> {
  const res = await fetch("/api/admin/accounts", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  const body = (await res.json().catch(() => null)) as
    | { account?: PublicAccount; error?: string; errors?: string[] }
    | null;
  if (res.ok && body?.account) return { ok: true, account: body.account };
  return {
    ok: false,
    status: res.status,
    error: typeof body?.error === "string" ? body.error : `request failed (${res.status})`,
    errors: Array.isArray(body?.errors) ? body.errors : undefined,
  };
}

export function updateRole(
  accountId: string,
  role: WorkbenchRoleId,
): Promise<PublicAccount> {
  return sendJson<{ account: PublicAccount }>(
    "PATCH",
    `/api/admin/accounts/${accountId}/role`,
    { role },
  ).then((b) => b.account);
}

export function disableAccount(accountId: string): Promise<PublicAccount> {
  return sendJson<{ account: PublicAccount }>(
    "POST",
    `/api/admin/accounts/${accountId}/disable`,
  ).then((b) => b.account);
}

// --- Supervisor Memory Audit View (0.0.3 S20, FR-20) --------------------------

export function getMemoryAudit(caseId: string): Promise<MemoryAuditView> {
  return getJson<MemoryAuditView>(
    `/api/admin/memory-audit?case_id=${encodeURIComponent(caseId)}`,
  );
}

export function clearMemorySlot(
  caseId: string,
  slot: MemoryPreferenceSlot,
): Promise<{ slot: string; cleared: boolean }> {
  return sendJson<{ slot: string; cleared: boolean }>(
    "POST",
    `/api/admin/memory-audit/clear?case_id=${encodeURIComponent(caseId)}`,
    { slot },
  );
}

// --- L6 Agent-experience store (0.0.3 S22, FR-23) -----------------------------

export function listAgentExperience(): Promise<AgentExperienceEntry[]> {
  return getJson<{ entries: AgentExperienceEntry[] }>("/api/admin/agent-experience").then(
    (b) => b.entries,
  );
}

// --- L6 confirm gate: Accept/Reject (0.0.3 S24, FR-24) ------------------------

export function confirmExperience(id: string): Promise<AgentExperienceEntry> {
  return sendJson<{ entry: AgentExperienceEntry }>(
    "POST",
    `/api/admin/agent-experience/${encodeURIComponent(id)}/confirm`,
  ).then((b) => b.entry);
}

export function rejectExperience(id: string): Promise<AgentExperienceEntry> {
  return sendJson<{ entry: AgentExperienceEntry }>(
    "POST",
    `/api/admin/agent-experience/${encodeURIComponent(id)}/reject`,
  ).then((b) => b.entry);
}

// --- Aggregate-metrics admin panel (0.0.3 S26, FR-28) -------------------------

export function getAggregateMetrics(): Promise<AggregateMetrics> {
  return getJson<AggregateMetrics>("/api/admin/metrics");
}

// --- Customer Memory retention sweep admin panel (0.0.3 S28, FR-30) ----------

export function getRetentionStatus(): Promise<RetentionStatus> {
  return getJson<RetentionStatus>("/api/admin/retention");
}

export function triggerRetentionSweep(): Promise<RetentionSweepQueued> {
  return sendJson<RetentionSweepQueued>("POST", "/api/admin/retention/sweep");
}
