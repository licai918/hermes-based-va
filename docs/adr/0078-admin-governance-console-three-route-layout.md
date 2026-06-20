# Admin Governance Console three-route layout

The first-version **Admin Governance Console** uses the **Supervisor Admin Profile** on a separate entry from **Copilot Workbench** per ADR-0039. It does not expose customer-facing send tools, **Copilot Draft Action**, or live external-service customer-read tools.

Governance pages use three independent routes that map one-to-one to v1 admin **Domain Adapter Tools**:

| Route | Tool | Primary actions |
|-------|------|-----------------|
| `/admin/knowledge` | `toee_knowledge_ops` | Read and edit **Required Operational Policy Slot** drafts, complete **Knowledge Gap Prompt** slots, `submit_for_eval`, `rollback_published_policy` |
| `/admin/eval` | `toee_eval_review` | `list_eval_runs`, `get_eval_run`, `sign_off_medium_failure`, `promote_pending_policy` |
| `/admin/accounts` | `toee_workbench_admin` | `list_accounts`, `create_account`, `update_account_role`, `disable_account` |

Each route is a top-level navigation destination. The console does not use a single-tabbed `/admin` hub in v1.

**Workbench Supervisor** and **Workbench Admin** users may access all three routes when their role includes the corresponding governance duties. **Customer Service Rep** users do not receive **Admin Governance Console** navigation in v1.

Read-only operational evidence needed during governance review may use `toee_workbench_read` and `toee_knowledge_search` from the relevant route context, but case drafting and customer send remain on the **Copilot Workbench** entry.

**Considered options:** one `/admin` page with Knowledge, Eval, and Accounts tabs (rejected—mixes unrelated workflows and makes deep-linking harder); knowledge hub with eval and accounts nested only under publish flow (rejected—account administration and eval sign-off are not sub-steps of slot editing); merge admin governance into Copilot navigation (rejected—ADR-0039 keeps profiles separate).
