# Supervisor Admin governance tool v1 actions

The **Supervisor Admin Profile** uses three governance **Domain Adapter Tools** with fixed v1 action enums.

## toee_knowledge_ops

| Action | Purpose |
|--------|---------|
| `get_policy_slots` | Read **Required Operational Policy Slot** and draft or published content state |
| `update_policy_slot` | Update draft text for an operational policy slot |
| `submit_for_eval` | Move updated operational policy into **Pending Eval Knowledge** |
| `rollback_published_policy` | Roll back external-effective **Published Operational Policy** to a prior approved version through governed workflow |

## toee_eval_review

| Action | Purpose |
|--------|---------|
| `list_eval_runs` | List **Launch Eval Gate** and publish-eval runs |
| `get_eval_run` | Read one eval run with scenario results and severity |
| `sign_off_medium_failure` | Record supervisor sign-off for medium-severity eval failures |
| `promote_pending_policy` | Promote eval-passed **Pending Eval Knowledge** to **Published Operational Policy** |

## toee_workbench_admin

| Action | Purpose |
|--------|---------|
| `list_accounts` | List **Workbench Account** records and roles |
| `create_account` | Create a **Workbench Account** |
| `update_account_role` | Change workbench role assignment |
| `disable_account` | Disable a **Workbench Account** |

These tools do not register customer-facing send tools or live external-service business reads for customer answers. `promote_pending_policy` and `submit_for_eval` must stay linked to the **Knowledge Publish Eval Gate**.

**Considered options:** merge all admin governance into one tool (rejected—blurs knowledge, eval, and account administration); allow direct publish without eval (rejected—ADR-0040); let Supervisor Admin send Textline replies through admin tools (rejected—ADR-0038).
