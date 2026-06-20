# Standard JSON eval report for launch and publish eval runs

The **Launch Eval Runner** writes one standard JSON eval report per run to `eval/reports/<run_id>.json`. Reports are the source of truth for `toee_eval_review.list_eval_runs` and `toee_eval_review.get_eval_run`, whether the run is imported into staging Hermes or read directly from the repository in CI.

Required report fields:

- `run_id`
- `suite` — such as `text_first_launch`, `email_go_live`, or `policy_publish`
- `model_slug`, `prompt_version`, and `knowledge_version`
- `scenarios[]` with scenario id, pass or fail, failed assertions, and severity
- `summary` with total, passed, `failed_high`, and `failed_medium`
- `signoff_required` when medium-severity failures remain

Go-live and publish promotion are blocked when `failed_high` is greater than zero. Medium failures require `sign_off_medium_failure` before promotion when `signoff_required` is true.

**Considered options:** exit-code-only runner output (rejected—no structured review or audit); direct database writes without report files (rejected—weak CI artifact trail); separate report formats per suite (rejected—harder for `toee_eval_review`).
