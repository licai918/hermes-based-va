# Copilot audit list columns and default sort

The read-only audit routes `/copilot/audit/auto-handled` and `/copilot/audit/sales-outreach` use full-width list layouts without the **Copilot Gateway** per ADR-0081. v1 defines a shared list skeleton plus route-specific columns.

## Shared list columns

Both audit lists show:

| Column | Purpose |
|--------|---------|
| Channel | SMS, email, or voice source for the record |
| Identity or sender summary | Verified customer label, unmatched label, or non-customer sender hint |
| Last message preview | Short preview of the latest inbound or outbound turn |
| Last activity time | Most recent conversation or case activity timestamp |
| Outcome or status | High-level result such as auto-resolved, case-created, or open audit record |

## Auto-Handled Audit View columns

`/copilot/audit/auto-handled` adds:

| Column | Purpose |
|--------|---------|
| Tool summary | Short summary of key tool calls used during the auto-handled turn |
| Tool failure flag | Visible when the interaction involved failed or unavailable tools before escalation or closure |

These rows represent **Auto-Handled Interaction** records, not **Human Intervention Case** queue items.

## Sales Outreach Audit View columns

`/copilot/audit/sales-outreach` adds:

| Column | Purpose |
|--------|---------|
| Case ID | Identifier for the low-priority `sales_outreach` **Follow-up Case** |
| Contact Reason | Fixed `sales_outreach` label for audit clarity |
| Created time | Case creation timestamp |

## Default sort

Both audit lists default to most recent activity first. Supervisors may apply simple filters such as channel or date range, but v1 does not add assignee or claim controls to audit lists.

Opening a specific audit record writes a **Workbench Audit Log** entry per ADR-0037 and ADR-0050.

**Considered options:** reuse the full **Case Queue** column set on audit pages (rejected—adds irrelevant assignee and claim fields); minimal timestamp-plus-preview lists only (rejected—weak compliance sampling); oldest-first default sort (rejected—supervisor sampling usually starts with recent traffic).
