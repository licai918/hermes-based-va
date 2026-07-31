// Browser-side client for the supervisor audit BFF routes (ADR-0037/0085/0086
// auto-handled, ADR-0050 sales-outreach, ADR-0154/0.0.4-S04 interaction review).
// The four list/get calls are GETs that ride the session cookie via getJson and
// surface a typed ApiError on non-2xx (e.g. 404) so views can render a friendly
// not-found state. submitInteractionReview is the one write (sendJson, POST) --
// review bar submissions on the two audit detail pages.
import type {
  AutoHandledRecord,
  ExternalReviewReasonTag,
  InteractionReview,
  InteractionReviewSubjectKind,
  InteractionReviewVerdict,
  WorkbenchCase,
} from "@/lib/gateway/types";
import { getJson, sendJson } from "./http";

const BASE = "/api/copilot/audit";

export function listAutoHandled(): Promise<{ records: AutoHandledRecord[] }> {
  return getJson<{ records: AutoHandledRecord[] }>(`${BASE}/auto-handled`);
}

export function getAutoHandled(
  recordId: string,
): Promise<{ record: AutoHandledRecord }> {
  return getJson<{ record: AutoHandledRecord }>(
    `${BASE}/auto-handled/${encodeURIComponent(recordId)}`,
  );
}

export function listSalesOutreach(): Promise<{ cases: WorkbenchCase[] }> {
  return getJson<{ cases: WorkbenchCase[] }>(`${BASE}/sales-outreach`);
}

export function getSalesOutreach(
  caseId: string,
): Promise<{ case: WorkbenchCase }> {
  return getJson<{ case: WorkbenchCase }>(
    `${BASE}/sales-outreach/${encodeURIComponent(caseId)}`,
  );
}

export function submitInteractionReview(input: {
  subjectKind: InteractionReviewSubjectKind;
  subjectId: string;
  verdict: InteractionReviewVerdict;
  reasonTags: ExternalReviewReasonTag[];
  comment?: string;
}): Promise<{ review: InteractionReview }> {
  return sendJson<{ review: InteractionReview }>("POST", `${BASE}/review`, {
    subject_kind: input.subjectKind,
    subject_id: input.subjectId,
    verdict: input.verdict,
    reason_tags: input.reasonTags,
    ...(input.comment ? { comment: input.comment } : {}),
  });
}
