# toee_workbench_read v1 actions for Copilot and Admin read surfaces

`toee_workbench_read` exposes three v1 **Domain Adapter Tool Action** values for the **Internal Copilot Profile** and **Supervisor Admin Profile**:

| Action | Purpose |
|--------|---------|
| `get_case` | Read one **Follow-up Case** with channel-thread summary, tool-failure evidence, and current workflow metadata |
| `list_cases` | List workbench cases with filters such as queue view, **Contact Reason**, urgency, and audit-only views including **Sales Outreach Audit View** |
| `get_audit_log` | Read **Workbench Audit Log** entries for a case, thread, or audit-view access event |

`toee_workbench_read` is read-only. It does not create or update cases, publish knowledge, or change workbench accounts.

**Considered options:** merge case detail and audit log into one action (rejected—audit sampling and case handling have different call patterns); add supervisor metrics actions in v1 (rejected—`list_cases` filters are enough for first launch); expose workbench reads only to Copilot (rejected—Supervisor Admin also needs audit evidence per ADR-0038).
