# Copilot audit detail read-only layout

When a **Workbench Supervisor** or **Workbench Admin** user opens a specific record from `/copilot/audit/auto-handled` or `/copilot/audit/sales-outreach`, the route shows a read-only detail page without the **Copilot Gateway**.

Opening a detail record writes a **Workbench Audit Log** entry with viewer, timestamp, and record identifier.

## Shared detail structure

Both audit detail pages use three read-only blocks:

1. **Summary header** — channel, identity or sender summary, key timestamps, and high-level outcome or status
2. **Conversation timeline** — full inbound and outbound turns for the sampled record in chronological order
3. **Evidence panel** — route-specific audit evidence described below

Detail pages do not expose claim, assign, resolve, draft, or send controls.

## Auto-Handled detail evidence

`/copilot/audit/auto-handled/:recordId` adds an evidence panel with:

- tool-call list for the auto-handled interaction
- short input and output summaries per tool call
- failed-tool markers and unavailable-system error classes when present
- outcome notes such as auto-resolved, escalated to case, or customer opt-out effects when applicable

## Sales Outreach detail evidence

`/copilot/audit/sales-outreach/:caseId` adds an evidence panel with:

- case metadata including case id, fixed `sales_outreach` **Contact Reason**, created time, and low-priority status
- Hermes first-response text sent or drafted for the outreach decline
- related audit-access metadata such as prior supervisor views when available from **Workbench Audit Log**

Sales outreach audit detail does not reuse the operational **Case Thread Context** action header from `/copilot`, because these records are audit-sampled only and not employee drafting queue items.

**Considered options:** conversation-only detail without tool evidence (rejected—weak auto-handled compliance review); reuse the operational case thread header with disabled action buttons (rejected—implies case handling workflow); allow contact-reason recategorize directly from audit detail (rejected—recategorize stays in operational `/copilot` case flow per ADR-0050).
