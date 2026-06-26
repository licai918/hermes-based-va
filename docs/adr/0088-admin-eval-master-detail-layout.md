# Admin eval review master-detail layout for eval runs

The `/admin/eval` route on the **Admin Governance Console** uses the **Supervisor Admin Profile** and `toee_eval_review` per ADR-0078.

## Master-detail layout

The page uses a two-pane master-detail layout:

**Left pane — eval run list**

Each row shows, at minimum:

- `run_id`
- `suite` such as `text_first_launch`, `email_go_live`, or `policy_publish`
- run timestamp
- summary pass or fail state
- `failed_high` and `failed_medium` counts
- linked `knowledge_version` or prompt version when present

The list defaults to most recent runs first.

**Right pane — eval report detail**

When a supervisor selects a run, the right pane shows the full JSON-backed report from ADR-0074, including:

- run metadata such as `model_slug`, `prompt_version`, and `knowledge_version`
- summary totals
- `scenarios[]` table with scenario id, pass or fail, failed assertions, and severity
- `signoff_required` state when medium-severity failures remain

## Action bar by report state

Action buttons appear on the right pane and vary by report eligibility:

| Action | When shown |
|--------|------------|
| Sign Off Medium Failure | `signoff_required` is true and `failed_high` is zero |
| Promote Pending Policy | report is a passing or medium-signed `policy_publish` run with promotable **Pending Eval Knowledge** |

`promote_pending_policy` must stay linked to **Knowledge Publish Eval Gate** rules from ADR-0040. Eval review does not edit policy slot text; that remains on `/admin/knowledge`.

**Considered options:** eval list only with separate detail route (rejected—extra navigation for a small admin team); embed eval results inside `/admin/knowledge` (rejected—blurs editing and review duties); allow promotion when `failed_high` is greater than zero (rejected—blocked by eval gate rules).
