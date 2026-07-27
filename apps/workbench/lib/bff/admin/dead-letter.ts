// Dead-letter operator view + governed Replay (0.0.4 S05, FR-13) for the Admin
// BFF (ADR-0093 admin route group). Pure and dependency-injected like the sibling
// admin/*.ts modules; the thin app/api/admin/dead-letter* routes wrap this with
// withSession + createAdminApiClient.
//
// Dispatches over the SUPERVISOR ADMIN Profile API (deps.ts's
// createAdminApiClient), not the Internal Copilot one admin/retention.ts and
// admin/metrics.ts use: toee_job_queue is allowlisted for supervisor_admin
// (hermes/toee_hermes/plugin/profiles.py). Both actions are also admin-only on
// the Hermes side (_AGENT_EXCLUDED_ACTIONS) -- never reachable from a live
// agent's tool loop.
//
// ROLE GATING: /admin/* is supervisor+admin (lib/auth/access.ts). That is the
// right level for an OPERATIONS surface and is deliberately broader than a
// credential surface would be -- a supervisor triaging stuck work should not need
// an admin account, while credentials should.
//
// list is READ, fail-open (dispatch, not dispatchWrite) -- same convention as
// handleGetRetentionStatusViaApi. Replay is a governed WRITE (it puts work back
// on the queue): dispatchWrite, fail-closed on a missing actor. The acting
// account rides HermesApiClient.actorAccountId from the signed-in session
// (ADR-0148) -- it is never a request param, and the route never reads one.
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { HermesApiError } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { json } from "../respond";

// What a dead job's own outbound attempt left behind (S03). `null` when the job
// never reached delivery -- which is what tells an operator a replay will
// genuinely send.
export interface DeadJobOutbound {
  status: string;
  skipCount: number;
  lastError: string | null;
}

export interface DeadJob {
  jobId: string;
  type: string;
  payloadSummary: Record<string, unknown>;
  attempts: number;
  maxAttempts: number;
  lastError: string | null;
  runAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  // Per-job-type replay safety, decided server-side (job_queue.py's
  // REPLAY_BLOCKED_JOB_TYPES). The panel disables the button and shows the
  // reason; the handler denies the call regardless, so a stale list cannot
  // sneak an l6_review replay through.
  replayable: boolean;
  replayBlockedReason: string | null;
  outbound: DeadJobOutbound | null;
}

// An outbound_send row that needs a human although no dead-letter row exists.
// `bucket` is one of send_failed | mirror_missing | stale_intent -- see the
// handler docstring for what each means and what an operator should do.
export interface StuckOutbound {
  bucket: string;
  slot: string;
  idempotencyKey: string;
  jobId: string | null;
  eventId: string;
  conversationId: string;
  channel: string;
  status: string;
  skipCount: number;
  lastError: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

// One `job_replayed` audit row, named to an account. FR-13 asks for a VISIBLE
// audit row; the handler writes it with target_type='job' and every other
// workbench audit view is case- or record-scoped, so this short tail is where a
// replay's provenance can actually be seen (and the only place it survives a
// replay that SUCCEEDS and takes its job off the dead list).
export interface RecentReplay {
  jobId: string;
  type: string | null;
  accountId: string | null;
  actorUsername: string | null;
  createdAt: string | null;
}

export interface DeadLetterView {
  jobs: DeadJob[];
  outbound: StuckOutbound[];
  recentReplays: RecentReplay[];
}

export interface ReplayReceipt {
  jobId: string;
  type: string | null;
  status: string;
}

function malformed(detail: string): never {
  throw new HermesApiError(
    "unexpected_error",
    `malformed dead-letter payload: ${detail}`,
  );
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string") malformed(field);
  return value as string;
}

function requireNullableString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") malformed(field);
  return value as string;
}

function requireNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || Number.isNaN(value)) malformed(field);
  return value as number;
}

function requireObject(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    malformed(field);
  }
  return value as Record<string, unknown>;
}

function requireArray(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) malformed(field);
  return value as unknown[];
}

function mapOutboundOnJob(value: unknown): DeadJobOutbound | null {
  if (value === null || value === undefined) return null;
  const r = requireObject(value, "outbound");
  return {
    status: requireString(r.status, "outbound.status"),
    skipCount: requireNumber(r.skip_count, "outbound.skip_count"),
    lastError: requireNullableString(r.last_error, "outbound.last_error"),
  };
}

function mapDeadJob(raw: unknown): DeadJob {
  const r = requireObject(raw, "jobs[]");
  return {
    jobId: requireString(r.job_id, "job_id"),
    type: requireString(r.type, "type"),
    payloadSummary: requireObject(r.payload_summary ?? {}, "payload_summary"),
    attempts: requireNumber(r.attempts, "attempts"),
    maxAttempts: requireNumber(r.max_attempts, "max_attempts"),
    lastError: requireNullableString(r.last_error, "last_error"),
    runAt: requireNullableString(r.run_at, "run_at"),
    createdAt: requireNullableString(r.created_at, "created_at"),
    updatedAt: requireNullableString(r.updated_at, "updated_at"),
    // Strict on purpose: a missing `replayable` must NOT default to true, or a
    // backend shape change would silently re-open replay for l6_review.
    replayable: typeof r.replayable === "boolean" ? r.replayable : malformed("replayable"),
    replayBlockedReason: requireNullableString(
      r.replay_blocked_reason,
      "replay_blocked_reason",
    ),
    outbound: mapOutboundOnJob(r.outbound),
  };
}

function mapStuckOutbound(raw: unknown): StuckOutbound {
  const r = requireObject(raw, "outbound[]");
  return {
    bucket: requireString(r.bucket, "bucket"),
    slot: requireString(r.slot, "slot"),
    idempotencyKey: requireString(r.idempotency_key, "idempotency_key"),
    jobId: requireNullableString(r.job_id, "job_id"),
    eventId: requireString(r.event_id, "event_id"),
    conversationId: requireString(r.conversation_id, "conversation_id"),
    channel: requireString(r.channel, "channel"),
    status: requireString(r.status, "status"),
    skipCount: requireNumber(r.skip_count, "skip_count"),
    lastError: requireNullableString(r.last_error, "last_error"),
    createdAt: requireNullableString(r.created_at, "created_at"),
    updatedAt: requireNullableString(r.updated_at, "updated_at"),
  };
}

function mapRecentReplay(raw: unknown): RecentReplay {
  const r = requireObject(raw, "recent_replays[]");
  return {
    jobId: requireString(r.job_id, "recent_replays[].job_id"),
    type: requireNullableString(r.type, "recent_replays[].type"),
    accountId: requireNullableString(r.account_id, "recent_replays[].account_id"),
    actorUsername: requireNullableString(
      r.actor_username,
      "recent_replays[].actor_username",
    ),
    createdAt: requireNullableString(r.created_at, "recent_replays[].created_at"),
  };
}

export function mapDeadLetterView(raw: unknown): DeadLetterView {
  const r = requireObject(raw, "root");
  return {
    jobs: requireArray(r.jobs, "jobs").map(mapDeadJob),
    outbound: requireArray(r.outbound, "outbound").map(mapStuckOutbound),
    // Deliberately NOT strict like `replayable`: this list is provenance
    // display, and a backend that omits it cannot re-open a blocked action --
    // whereas a defaulted `replayable` would. A backend without the field (the
    // mock driver) shows an empty log rather than 502-ing the whole panel.
    recentReplays: requireArray(
      r.recent_replays ?? [],
      "recent_replays",
    ).map(mapRecentReplay),
  };
}

export function mapReplayReceipt(raw: unknown): ReplayReceipt {
  const r = requireObject(raw, "root");
  return {
    jobId: requireString(r.job_id, "job_id"),
    type: requireNullableString(r.type, "type"),
    status: requireString(r.status, "status"),
  };
}

export async function handleListDeadLettersViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = await client.dispatch("toee_job_queue", "list_dead_letters", {});
    return json(mapDeadLetterView(data));
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleReplayJobViaApi(
  client: HermesApiClient,
  jobId: unknown,
): Promise<Response> {
  if (typeof jobId !== "string" || jobId === "") {
    return hermesErrorToProblem(
      new HermesApiError("not_found", "jobId is required"),
    );
  }
  try {
    // No bulk replay in v1 (PRD default): one job id, one call. The actor is NOT
    // in these params -- it rides the client's actorAccountId (ADR-0148).
    const data = await client.dispatchWrite("toee_job_queue", "replay_job", {
      job_id: jobId,
    });
    return json(mapReplayReceipt(data));
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
