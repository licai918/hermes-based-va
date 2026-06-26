# Launch eval runner CLI contract placeholder

The **Launch Eval Runner** is a repository CLI that executes `eval/scenarios/*.yaml` against the **External Customer Service Profile** with mock **Domain Adapter** responses.

## Commands

Root package scripts expose:

- `pnpm eval` — default `text_first_launch` suite
- `pnpm eval -- --suite text_first_launch`
- `pnpm eval -- --suite email_go_live`
- `pnpm eval -- --suite text_first_launch --scenario 01`
- `pnpm eval -- --suite policy_publish --slot standard_exception_scripts`

## Inputs

- `eval/mocks/base.yaml`
- one or more scenario YAML files selected by suite or scenario id from `eval/scenarios/` and `eval/scenarios/email/`
- `eval/policy_slot_map.yaml` for `policy_publish`

## Outputs

- `eval/reports/<run_id>.json` per ADR-0074
- non-zero exit code when `summary.failed_high` is greater than zero

The runner implementation may live under `packages/eval-runner` or `scripts/eval/` in a later change. v1 fixture delivery does not require the executable runner to exist yet.

**Considered options:** store reports only in Hermes Native Memory (rejected—weak CI artifact trail); run eval only through the workbench UI (rejected—blocks CI and local developer workflow).
