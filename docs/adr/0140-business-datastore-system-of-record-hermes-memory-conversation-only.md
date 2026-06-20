# Toee business datastore is system-of-record; Hermes native memory is conversation-only

## Context

The same investigation behind ADR-0139 established what Hermes "native memory"
actually is: `MEMORY.md` (~2,200 chars) and `USER.md` (~1,375 chars) curated
agent-notes injected at session start, plus `session_search` over a SQLite FTS5
transcript store, plus optional external memory providers (Honcho, Mem0, …). It
is **bounded agent conversation memory, not a structured business datastore**.

Earlier ADRs (0110–0116) described **Hermes Native Memory** as the structured
system-of-record for the **Identity Graph**, **Customer Memory** preference slots,
**Session Identity Snapshot**, conversation/case/audit records, **Workbench
Accounts**, knowledge versions, and eval runs. Hermes cannot serve that role:
those are relational, queryable, multi-tenant, retention-governed records, not a
few kilobytes of agent notes.

## Decision

Split memory by responsibility:

- **Toee Business Datastore (Postgres) is the system-of-record.** It holds the
  Identity Graph + Session Identity Snapshot, Customer Memory slots (bound to
  `shopifyCustomerId`, or provisionally `channelIdentityId`), Customer Thread /
  SMS Session / MessageTurn, Cases + Workbench Audit Log, Workbench Accounts,
  knowledge versions + publish state, and eval-run records. Retention periods
  (ADR-0004) are enforced here. It is activated on demand per ADR-0025 (Cloud SQL
  on Cloud Run), not provisioned as a day-one fixed bundle.
- **Hermes native memory stays conversation-only.** `MEMORY.md` / `USER.md` /
  `session_search` provide per-profile agent conversation continuity. They are
  never the business source of truth.
- **Per-turn injection** of the Session Identity Snapshot and a compact Customer
  Memory preference block uses the `toee_hermes` plugin `pre_llm_call` hook, which
  appends to the user turn (not the system prompt, preserving the prefix cache).
  This is the faithful implementation of ADR-0113 "lightweight injection reads."
- **Governed reads/writes** of Customer Memory go through the `toee_customer_memory`
  plugin tool (ADR-0114) against the datastore — not the Hermes built-in `memory`
  tool, which remains the agent's own conversation notes.

This reconciles ADR-0110–0116: their slot model, write-source rules, provisional
merge, entity-id hierarchy, and retention still hold, but their storage substrate
is the Toee Business Datastore, with Hermes memory layered on top for
conversational recall.

## Considered options

- **Postgres system-of-record + Hermes memory for conversation (chosen).**
  Relational, queryable, retention- and audit-capable; Hermes does what it is good
  at.
- **Force business entities into MEMORY.md / an external memory provider
  (rejected).** Character-bounded, not relational, no retention/audit guarantees,
  not keyable across many customers.
- **No database, rely on `session_search` (rejected).** Transcript search is not a
  queryable business store for cases, accounts, identity, or eval records.
