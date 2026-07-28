// Workbench Gateway domain types (ADR-0027 Copilot Gateway, ADR-0029 assignment +
// audit, ADR-0079 case queue, ADR-0082 thread context, ADR-0037 auto-handled,
// ADR-0085/0086 audit views). These are the workbench's WIRE shapes: hermes-map.ts
// validates each snake_case datastore row onto them (0.0.4 S09 deleted the
// in-memory store they were originally written for; the shapes did not change).
import {
  MEMORY_PREFERENCE_SLOTS,
  type DraftOutcome,
  type DraftRatingVerdict,
  type ExternalReviewReasonTag,
  type InteractionReviewVerdict,
  type InternalReviewReasonTag,
  type MemoryPreferenceSlot,
} from "@toee/shared";

// Re-exported so the rest of the BFF/gateway layer imports the slot union from
// "./types" alongside everything else, without drifting from the @toee/shared
// contract's own slot names (ADR-0111, S07/FR-6).
export type { MemoryPreferenceSlot };

// Re-exported so 0.0.4 S04 review code imports the EXTERNAL Review Reason Tag
// vocabulary + verdict from "./types" alongside everything else, without
// drifting from the @toee/shared feedback.ts contract (ADR-0154).
export type { ExternalReviewReasonTag, InteractionReviewVerdict };

// Re-exported so 0.0.4 S07 draft-rating code imports the INTERNAL Review Reason
// Tag vocabulary + verdict from "./types" alongside everything else, same
// discipline as the EXTERNAL pair above (ADR-0154).
export type { InternalReviewReasonTag, DraftRatingVerdict };

// Re-exported so 0.0.4 S09's implicit outcome-capture code (feedback.ts's
// record_draft_outcome branch) imports it from "./types" alongside everything
// else, same discipline as DraftRatingVerdict above (ADR-0154).
export type { DraftOutcome };

export type CaseChannel = "sms" | "email" | "voice";

export type CaseStatus = "open" | "in_progress" | "resolved";

// Human Intervention Case / Follow-up Case row. Fields cover the ADR-0079 queue
// columns plus the ADR-0082 sticky-header metadata. `contactReason` is a free
// string label (e.g. "order_status", "unknown", "sales_outreach", non-customer
// reasons) rather than a closed enum so launch playbooks can extend it.
export interface WorkbenchCase {
  caseId: string;
  channel: CaseChannel;
  identitySummary: string;
  contactReason: string;
  urgent: boolean;
  status: CaseStatus;
  assigneeAccountId: string | null;
  resolvedByAccountId: string | null;
  threadId: string;
  lastMessagePreview: string;
  toolFailure: boolean;
  // Governed SMS send (ADR-0083) is only enabled on SMS cases with an
  // active SMS Session on the current thread.
  smsSessionActive: boolean;
  openedAt: number;
  lastActivityAt: number;
  // Sampling coverage (0.0.4 S05, FR-6): ANY interaction_review row exists for
  // this case, by any reviewer -- "has this been sampled", not "did I review
  // it". Only `list_sales_outreach` populates this (a single batched join, not
  // per-row); optional because the general case queue read (`list_cases`)
  // never sets it -- absent reads as not-reviewed, same as `false`.
  reviewed?: boolean;
  // US-7/FR-5 (gap fix): the CURRENT ACCOUNT's own latest review of this
  // subject, if any -- what ReviewBar renders on load so reopening a record
  // shows the reviewer's own prior verdict. Only `get_sales_outreach`
  // populates this; absent/null reads as "I haven't reviewed this", distinct
  // from `reviewed` above (which is "has anyone").
  myReview?: InteractionReview | null;
}

export type ThreadAuthor = "customer" | "hermes" | "workbench";

// One read-only turn in a Case Thread Context timeline (ADR-0082). Prior
// Auto-Handled turns stay visible but de-emphasized (`autoHandled: true`); the
// active Human Intervention segment is highlighted (`activeCaseSegment: true`).
export interface ThreadMessage {
  messageId: string;
  threadId: string;
  at: number;
  author: ThreadAuthor;
  channel: CaseChannel;
  body: string;
  autoHandled: boolean;
  activeCaseSegment: boolean;
}

// Workbench Audit Log entry (ADR-0029). Records actor, timestamp, action, and the
// case or audit record it concerns. Written for login, case view, claim/assign,
// draft generation, status change, resolution, governed send, and audit views.
export type AuditAction =
  | "case_view"
  | "claim_case"
  | "assign_case"
  | "update_priority"
  | "update_contact_reason"
  | "resolve_case"
  | "draft_generated"
  | "sms_send"
  | "audit_view";

export interface AuditLogEntry {
  entryId: string;
  at: number;
  actorAccountId: string;
  actorUsername: string;
  action: AuditAction;
  caseId?: string;
  recordId?: string;
  detail?: string;
}

// One tool call captured for an Auto-Handled Interaction (ADR-0086 evidence
// panel): short input/output summaries plus an optional unavailable-system error
// class when the call failed.
export interface ToolCallEvidence {
  tool: string;
  action: string;
  inputSummary: string;
  outputSummary: string;
  errorClass?: string;
}

// Auto-Handled Interaction record (ADR-0037). Distinct from WorkbenchCase: these
// never enter the work queue; supervisors browse them read-only.
export interface AutoHandledRecord {
  recordId: string;
  channel: CaseChannel;
  identitySummary: string;
  lastMessagePreview: string;
  lastActivityAt: number;
  outcome: string;
  toolSummary: string;
  toolFailure: boolean;
  timeline: ThreadMessage[];
  toolCalls: ToolCallEvidence[];
  // Sampling coverage (0.0.4 S05, FR-6): ANY interaction_review row exists for
  // this record, by any reviewer -- see WorkbenchCase.reviewed for the same
  // semantics. Only `list_auto_handled` populates this; `get_auto_handled`
  // (detail) never sets it -- absent reads as not-reviewed, same as `false`.
  reviewed?: boolean;
  // US-7/FR-5 (gap fix): see WorkbenchCase.myReview for the same semantics.
  // Only `get_auto_handled` populates this.
  myReview?: InteractionReview | null;
}

// The EXTERNAL mechanism's subject: one Auto-Handled Interaction record or one
// sales_outreach Follow-up Case (ADR-0154, 0.0.4 S04). Mirrors
// INTERACTION_REVIEW_SUBJECT_KINDS in the Python plugin schemas.
export type InteractionReviewSubjectKind =
  | "auto_handled_record"
  | "sales_outreach_case";

// A supervisor/admin's pass/fail judgment (toee_feedback.submit_interaction_review,
// ADR-0154, 0.0.4 S03/S04). Append-only on the datastore: a re-review is a new row,
// never an update -- the BFF/UI treat the latest one per subject as "the" review.
export interface InteractionReview {
  reviewId: string;
  subjectKind: InteractionReviewSubjectKind;
  subjectId: string;
  verdict: InteractionReviewVerdict;
  reasonTags: ExternalReviewReasonTag[];
  comment: string | null;
  reviewerAccountId: string;
  createdAt: number;
}

// Which copilot draft surface generated a draft (toee_feedback.submit_draft_rating
// / record_draft_outcome, ADR-0154, 0.0.4 S06/S07). Mirrors the draft_kind enum in
// the Python plugin schemas (hermes/toee_hermes/plugin/schemas.py).
export type DraftKind = "sms" | "email" | "note";

// A rep's thumbs up/down on one copilot draft (toee_feedback.submit_draft_rating,
// 0.0.4 S06/S07). Append-only, same as InteractionReview -- a re-rating is a new
// row, not an overwrite.
export interface DraftRating {
  ratingId: string;
  caseId: string;
  draftCorrelationId: string;
  draftKind: DraftKind;
  verdict: DraftRatingVerdict;
  reasonTags: InternalReviewReasonTag[];
  comment: string | null;
  repAccountId: string;
  createdAt: number;
}

// Assignee filter modes for the queue (ADR-0079). Reps default to
// `mine_or_unassigned`; supervisors/admins may widen to `all`.
export type AssigneeFilterMode = "all" | "mine" | "unassigned" | "mine_or_unassigned";

export interface CaseListFilter {
  // Defaults to ["open", "in_progress"] (resolved hidden) when omitted.
  statuses?: CaseStatus[];
  assignee?: { mode: AssigneeFilterMode; accountId?: string };
}

// Customer Memory preferences (ADR-0111/0114, PAC-4/S17). A case's four v1
// preference slots as read/corrected from the Workbench; any slot not yet set is
// simply absent rather than present with an empty value.
//
// Re-exported (not re-declared) from @toee/shared (S07, FR-6; formerly
// domain-adapters until S09, FR-7): MEMORY_PREFERENCE_SLOTS is the single
// source, so a fifth slot can't silently drift between the two copies.
export const PREFERENCE_SLOTS: readonly MemoryPreferenceSlot[] = MEMORY_PREFERENCE_SLOTS;

export type CustomerPreferences = Partial<Record<MemoryPreferenceSlot, string>>;

// Supervisor Memory Audit View (0.0.3 S20, FR-20): a customer's 4 slots with
// full write attribution -- source/actor/timestamps -- plus the append-only
// workbench_audit_log trail for the same binding (dismissed proposals,
// attributed clears). `binding_key` never crosses this boundary, same rule as
// CustomerPreferences/mapPreferences above -- it is the customer's raw
// identity key.
export type MemoryWriteSource =
  | "customer_explicit"
  | "employee_confirmed"
  | "copilot_agent"
  | "merged_provisional";

export interface MemorySlotAttribution {
  slot: MemoryPreferenceSlot;
  value: string;
  source: MemoryWriteSource | null;
  actorAccountId: string | null;
  evidence: string | null;
  createdAt: number;
  updatedAt: number;
}

// Not a closed enum: the audit trail carries whatever governed actions land in
// workbench_audit_log (proposal_dismissed, preference_cleared, future kinds), so
// an unrecognized action string is passed through rather than rejected. (S16
// surfaces *accepted* proposals from employee_confirmed slots, not by joining
// rows into this history — but keeping the field open still avoids brittle
// rejection of any action this mapper doesn't yet know about.)
export interface MemoryAuditEntry {
  entryId: string;
  at: number;
  actorAccountId: string | null;
  actorUsername?: string | null;
  action: string;
  slot: string | null;
  detail?: string;
  // S16 (FR-17): the proposed value for a proposal_dismissed row, lifted from
  // ``details.value`` (S15 writes it) the same way ``slot`` is lifted from
  // ``details.slot`` above -- so the proposal-history section can show what
  // was proposed, not just that something was dismissed.
  value?: string;
  // 0.0.5 S07 (FR-9): the old->new pair for a preference_updated row, lifted
  // from ``details.old_value``/``details.new_value`` the same way ``value``
  // is lifted above -- so the write-history section can render what changed,
  // not just that a change happened.
  oldValue?: string;
  newValue?: string;
}

export interface MemoryAuditView {
  slots: MemorySlotAttribution[];
  history: MemoryAuditEntry[];
}

// L6 Agent-experience store (0.0.3 S22, FR-23/NFR-3): "what the agent learns
// from doing the job" -- a NEW governed store distinct from L4 Customer Memory
// above and L5's authored corpus. Proposals persist with status="proposed"
// directly (the propose/confirm gate is status-based, not an envelope): an
// entry here is inert until an admin flips it (S24 confirm/reject queue,
// out of scope here -- this is a read-only list).
export type AgentExperienceKind = "note" | "procedure";
export type AgentExperienceStatus = "proposed" | "confirmed" | "rejected";

export interface AgentExperienceEntry {
  id: string;
  kind: AgentExperienceKind;
  status: AgentExperienceStatus;
  content: string;
  source: string;
  proposerContext: Record<string, unknown> | null;
  deciderAccountId: string | null;
  decidedAt: number | null;
  createdAt: number;
}

// L7 Semantic Lexicon (0.0.5 S01/S02, FR-1/FR-3/FR-8): the governed store of the
// domain language the business speaks -- "TOEE" means "TOEE TIRE"; "2055516" and
// "205 55 16" are the same tire size. The seventh and last memory layer, distinct
// from L4 (per-customer PII), L5 (authored corpus) and L6 above.
export type LexiconEntryKind = "alias" | "normalizer" | "default_rule";
export type LexiconStatus = "proposed" | "confirmed" | "rejected" | "retired";
export type LexiconProvenance =
  | "admin_manual"
  | "conversation_confirmed"
  | "feedback_derived";

export interface LexiconEntry {
  id: string;
  domain: string;
  entryKind: LexiconEntryKind;
  surfaceForm: string;
  canonicalForm: string;
  status: LexiconStatus;
  provenance: LexiconProvenance;
  evidence: string | null;
  proposerContext: Record<string, unknown> | null;
  // "A PII span WAS removed from evidence/proposer_context." The FALSE case is
  // NOT a clean bill of health: D2's keep exemption waives a span that exactly
  // equals this entry's own surface/canonical form (it must -- the seeded
  // "205 55 16" matches the phone pattern), and the waiver is recorded only in
  // the audit row's `pii_keep_exempt`. Any UI showing this must say what it means.
  piiRedacted: boolean;
  deciderAccountId: string | null;
  // D20: an `admin_manual` claim with nobody attached. Only reachable for rows
  // written between S01 and S02, before the provenance path became fail-closed --
  // derived server-side so the console can render it distinctly from an entry a
  // named admin actually approved.
  provenanceUnattributed: boolean;
  decidedAt: number | null;
  // Materialized by a scheduled rollup (D6), never an in-turn UPDATE.
  hitCount: number;
  createdAt: number;
  updatedAt: number | null;
}
