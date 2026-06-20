# Email go-live eval fixtures as independent channel files

`email_go_live` **Launch Eval** fixtures use separate YAML files from SMS `text_first_launch` fixtures. Each file keeps the same numeric `scenario_id` as ADR-0010 but declares `suite: email_go_live` and `channel: email`.

## Repository layout

SMS fixtures remain under `eval/scenarios/` unchanged. Email fixtures live in a dedicated subdirectory:

```text
eval/
  mocks/
    base.yaml
  scenarios/
    14-non-customer-government.yaml
    ...
    email/
      14-non-customer-government-email.yaml
      19-email-verified-customer.yaml
      ...
      23-email-alternate-address-rejected.yaml
```

## File naming

Email files use the same numeric id prefix and kebab slug as their SMS counterparts where applicable, with an `-email` suffix before `.yaml`:

```text
email/{id}-{kebab-slug}-email.yaml
```

Examples:

- `email/14-non-customer-government-email.yaml`
- `email/19-email-verified-customer.yaml`
- `email/23-email-alternate-address-rejected.yaml`

`scenario_id` inside the file must match the numeric id prefix. The runner selects files by `suite`, not by directory alone.

## Suite scope

| `suite` value | Scenario ids | Channel |
|---------------|--------------|---------|
| `text_first_launch` | 01–18, 24–26 | `textline` |
| `email_go_live` | 14–18, 19–23 | `email` |

Scenarios 14–18 exist twice in the repository: once for SMS and once for email. Assertions and inbound wording may differ per channel while preserving the same behavioral intent from ADR-0010 and ADR-0051.

Scenarios 19–23 exist only under `eval/scenarios/email/`. They are not part of `text_first_launch`.

## Runner selection

The **Launch Eval Runner** loads scenario files whose `suite` field matches the requested run. SMS and email files with the same `scenario_id` are distinct fixtures, not aliases.

**Considered options:** add `channels: [textline, email]` to existing SMS YAML (rejected—dual-channel turns and assertions are harder to maintain); create only 19–23 and skip email reruns of 14–18 (rejected—ADR-0051 requires non-customer parity on email fixtures); use different scenario ids for email such as E14 (rejected—breaks ADR-0076 suite tables and policy publish mapping).
