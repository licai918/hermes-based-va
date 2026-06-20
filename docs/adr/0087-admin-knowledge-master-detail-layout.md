# Admin KnowledgeOps master-detail layout for policy slots

The `/admin/knowledge` route on the **Admin Governance Console** uses the **Supervisor Admin Profile** and `toee_knowledge_ops` per ADR-0078.

## Master-detail layout

The page uses a two-pane master-detail layout:

**Left pane — slot list**

- lists all six **Required Operational Policy Slots** from ADR-0003 as fixed entries
- shows a status badge per slot: `Empty`, `Draft`, `Pending Eval`, `Published`, or `Gap`
- highlights slots with active **Knowledge Gap Prompt** requests

**Right pane — slot editor**

When a supervisor selects a slot, the right pane shows:

- slot title and identifier
- draft or pending policy text editor
- owner and review date fields
- published-version reference and short version history summary when available

## Action bar by state

Action buttons appear on the right pane and vary by slot state:

| Action | When shown |
|--------|------------|
| Save Draft | editable draft or gap-fill state |
| Submit for Eval | draft ready to enter **Pending Eval Knowledge** |
| Rollback Published | a prior published version exists and rollback is allowed |

`submit_for_eval` moves the slot into **Knowledge Publish Eval Gate** workflow per ADR-0040. `rollback_published_policy` uses governed rollback rules and does not bypass eval when the rolled-back version is not already the active published baseline.

The knowledge page does not host eval report review or account administration. Those remain on `/admin/eval` and `/admin/accounts`.

**Considered options:** single table with modal editor (rejected—weak context for long policy text); onboarding wizard only (rejected—poor fit for ongoing slot maintenance); combine knowledge editing and eval sign-off on one page (rejected—blurs KnowledgeOps and eval review responsibilities).
