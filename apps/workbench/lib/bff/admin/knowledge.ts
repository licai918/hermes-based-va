// KnowledgeOps slot handlers for the Admin BFF (ADR-0087 master-detail policy
// authoring over the six Required Operational Policy Slots, ADR-0003). Pure and
// dependency-injected; the thin app/api/admin/knowledge route files wrap these
// with withSession and inject the real KnowledgeStore singleton.
import { HermesApiClient, HermesApiError } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import type { PolicySlot, SlotStatus } from "../../gateway/knowledge-store";
import { json, problem } from "../respond";
import { type AdminDeps, readJsonBody } from "./deps";

export function handleListSlots(deps: AdminDeps): Response {
  return json({ slots: deps.knowledge.listSlots() });
}

export async function handleSaveDraft(
  req: Request,
  slotId: string,
  deps: AdminDeps,
): Promise<Response> {
  const body = await readJsonBody(req);
  const patch: { draftText?: string; owner?: string; reviewDate?: string } = {};
  if (typeof body?.draftText === "string") patch.draftText = body.draftText;
  if (typeof body?.owner === "string") patch.owner = body.owner;
  if (typeof body?.reviewDate === "string") patch.reviewDate = body.reviewDate;

  const slot = deps.knowledge.saveDraft(slotId, patch);
  if (!slot) return problem(404, "slot not found");
  return json({ slot });
}

export function handleSubmitSlot(slotId: string, deps: AdminDeps): Response {
  const result = deps.knowledge.submitForEval(slotId);
  if (result.ok) return json({ slot: result.slot });
  if (result.reason === "not_found") return problem(404, "slot not found");
  return problem(409, "slot has no draft to submit");
}

export function handleRollbackSlot(slotId: string, deps: AdminDeps): Response {
  const result = deps.knowledge.rollbackPublished(slotId);
  if (result.ok) return json({ slot: result.slot });
  if (result.reason === "not_found") return problem(404, "slot not found");
  return problem(409, "slot has no previous published version");
}

// --- Per-profile API cutover (ADR-0141/0145 Increment 6) ---------------------
// The Supervisor Admin knowledge-slot routes dispatch toee_knowledge_ops over the
// per-profile Hermes API when HERMES_ADMIN_API_URL/TOKEN are configured (else the
// in-memory KnowledgeStore). The list read uses dispatch (fail-open); the three
// governed mutations use dispatchWrite (fail-closed on the acting supervisor baked
// into the client), so a write can never land a NULL-actor audit row — the
// datastore enforces the same rule. The per-class error mapping turns a governed
// not_found/conflict into 404/409 (store-path status parity).

const SLOT_STATUSES = new Set<SlotStatus>([
  "empty",
  "draft",
  "pending_eval",
  "published",
  "gap",
]);

// Maps a snake_case workbench_policy_slot row from the per-profile API (ADR-0145)
// onto the wire PolicySlot, rejecting contract violations (missing id/title,
// unknown status) as governed HermesApiErrors so a bad upstream surfaces on the
// ADR-0090 banner rather than rendering garbage (mirrors mapPublicAccount).
export function mapPolicySlot(raw: unknown): PolicySlot {
  if (typeof raw !== "object" || raw === null) {
    throw new HermesApiError("unexpected_error", "malformed policy slot payload");
  }
  const r = raw as Record<string, unknown>;
  const slotId = typeof r.slot_id === "string" ? r.slot_id : "";
  if (!slotId) throw new HermesApiError("unexpected_error", "missing slot id");
  if (typeof r.title !== "string" || r.title.length === 0) {
    throw new HermesApiError("unexpected_error", "missing slot title");
  }
  if (typeof r.status !== "string" || !SLOT_STATUSES.has(r.status as SlotStatus)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown slot status: ${String(r.status)}`,
    );
  }
  // draft_text/published_text/owner/review_date are nullable; a provided string
  // (incl. "") is preserved, anything else is null — store-path parity.
  const orNull = (v: unknown): string | null => (typeof v === "string" ? v : null);
  return {
    slotId,
    title: r.title,
    status: r.status as SlotStatus,
    draftText: orNull(r.draft_text),
    publishedText: orNull(r.published_text),
    owner: orNull(r.owner),
    reviewDate: orNull(r.review_date),
    hasGapPrompt: r.has_gap_prompt === true,
  };
}

export async function handleListSlotsViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = (await client.dispatch(
      "toee_knowledge_ops",
      "get_policy_slots",
    )) as { slots?: unknown };
    const rows = Array.isArray(data?.slots) ? data.slots : [];
    return json({ slots: rows.map(mapPolicySlot) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleSaveDraftViaApi(
  req: Request,
  slotId: string,
  client: HermesApiClient,
): Promise<Response> {
  const body = await readJsonBody(req);
  // Same provided-field semantics as the store path: only forward present fields,
  // mapped to the snake_case the datastore reads.
  const params: Record<string, unknown> = { slot_id: slotId };
  if (typeof body?.draftText === "string") params.draft_text = body.draftText;
  if (typeof body?.owner === "string") params.owner = body.owner;
  if (typeof body?.reviewDate === "string") params.review_date = body.reviewDate;
  try {
    const result = (await client.dispatchWrite(
      "toee_knowledge_ops",
      "update_policy_slot",
      params,
    )) as { slot?: unknown };
    return json({ slot: mapPolicySlot(result.slot) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleSubmitSlotViaApi(
  slotId: string,
  client: HermesApiClient,
): Promise<Response> {
  try {
    const result = (await client.dispatchWrite(
      "toee_knowledge_ops",
      "submit_for_eval",
      { slot_id: slotId },
    )) as { slot?: unknown };
    return json({ slot: mapPolicySlot(result.slot) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleRollbackSlotViaApi(
  slotId: string,
  client: HermesApiClient,
): Promise<Response> {
  try {
    const result = (await client.dispatchWrite(
      "toee_knowledge_ops",
      "rollback_published_policy",
      { slot_id: slotId },
    )) as { slot?: unknown };
    return json({ slot: mapPolicySlot(result.slot) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// --- S11: corpus status + retrieval probe (FR-6) ------------------------------
// Both routes are API-only (no in-memory store fallback -- there is no corpus to
// fake): the thin app/api route returns 503 up front when the admin API client
// isn't configured (see createAdminApiClient), so these handlers can assume a
// real client.

// 0.0.4 S04 (FR-11): the re-ingest panel's status readback. Null when no
// re-ingest has ever been queued, or on a backend with no durable queue.
export type IngestJobStatus = {
  jobId: string;
  status: string;
  attempts: number;
  lastError: string | null;
  queuedAt: string | null;
  updatedAt: string | null;
};

export type CorpusStatus = {
  docCount: number;
  chunkCount: number;
  lastIngestAt: string | null;
  byType: { pageType: string; count: number }[];
  lastIngestJob: IngestJobStatus | null;
};

// Maps the snake_case toee_knowledge_ops.get_corpus_status payload onto the wire
// CorpusStatus, rejecting a malformed upstream as a governed HermesApiError
// (mirrors mapPolicySlot).
export function mapCorpusStatus(raw: unknown): CorpusStatus {
  if (typeof raw !== "object" || raw === null) {
    throw new HermesApiError("unexpected_error", "malformed corpus status payload");
  }
  const r = raw as Record<string, unknown>;
  const byType = Array.isArray(r.by_type) ? r.by_type : [];
  return {
    docCount: typeof r.doc_count === "number" ? r.doc_count : 0,
    chunkCount: typeof r.chunk_count === "number" ? r.chunk_count : 0,
    lastIngestAt: typeof r.last_ingest_at === "string" ? r.last_ingest_at : null,
    byType: byType.map((row) => {
      const rr = row as Record<string, unknown>;
      return {
        pageType: typeof rr.page_type === "string" ? rr.page_type : "",
        count: typeof rr.count === "number" ? rr.count : 0,
      };
    }),
    lastIngestJob: mapIngestJob(r.last_ingest_job),
  };
}

function mapIngestJob(raw: unknown): IngestJobStatus | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.job_id !== "string" || typeof r.status !== "string") return null;
  const orNull = (v: unknown): string | null => (typeof v === "string" ? v : null);
  return {
    jobId: r.job_id,
    status: r.status,
    attempts: typeof r.attempts === "number" ? r.attempts : 0,
    lastError: orNull(r.last_error),
    queuedAt: orNull(r.queued_at),
    updatedAt: orNull(r.updated_at),
  };
}

export type ReingestQueued = { jobId: string | null; status: string };

// S04 (FR-11): the re-ingest trigger 0.0.3 S11 shipped as a display-only stub.
// A governed dispatchWrite -- it TRUNCATEs and reloads the whole corpus, so it is
// fail-closed on the acting supervisor and audited on the Hermes side; the panel
// then reads the job back through get_corpus_status.
export async function handleTriggerReingestViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = (await client.dispatchWrite(
      "toee_knowledge_ops",
      "enqueue_corpus_reingest",
      {},
    )) as Record<string, unknown>;
    const jobId = typeof data?.job_id === "string" ? data.job_id : null;
    const status = typeof data?.status === "string" ? data.status : "queued";
    return json({ jobId, status } satisfies ReingestQueued);
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleGetCorpusStatusViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = await client.dispatch("toee_knowledge_ops", "get_corpus_status");
    return json({ status: mapCorpusStatus(data) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export type ProbeResult = {
  title: string;
  url: string | null;
  snippet: string;
};

function mapProbeResult(raw: unknown): ProbeResult {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  return {
    title: typeof r.title === "string" ? r.title : "",
    url: typeof r.url === "string" ? r.url : null,
    snippet: typeof r.snippet === "string" ? r.snippet : "",
  };
}

// Retrieval probe (S08's re-scoped layer-② evidence, per S11's scope addition):
// dispatches toee_knowledge_search.search_public_site through the admin profile
// API, hitting the REAL S09/S10 driver when the dispatch server runs with
// KNOWLEDGE_BACKEND=retriever. A blank query is rejected before dispatch (mirrors
// the KnowledgeDriver's own empty-query guard, but as a normal 400 -- there's no
// governed tool call to make yet).
export async function handleProbeQueryViaApi(
  req: Request,
  client: HermesApiClient,
): Promise<Response> {
  const body = await readJsonBody(req);
  const query = typeof body?.query === "string" ? body.query : "";
  if (!query.trim()) return problem(400, "query is required");
  try {
    const data = (await client.dispatch("toee_knowledge_search", "search_public_site", {
      query,
    })) as { results?: unknown };
    const rows = Array.isArray(data?.results) ? data.results : [];
    return json({ results: rows.map(mapProbeResult) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
