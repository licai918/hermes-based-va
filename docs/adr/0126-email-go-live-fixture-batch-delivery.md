# Email go-live launch eval fixture batch delivery

The `email_go_live` **Launch Eval** fixture batch is complete in the repository. It delivers the email-channel go-live gate defined in ADR-0010, ADR-0051, and ADR-0076.

## Suite scope

| `suite` | Scenario ids | Count |
|---------|--------------|-------|
| `email_go_live` | 14–18, 19–23 | 10 |

Scenarios 14–18 are email-channel reruns of the SMS non-customer parity set. Scenarios 19–23 are email-specific identity and ingress cases.

## Repository layout

```text
eval/
  mocks/
    base.yaml                 # email_verified_a, email_unmatched_a, email_ambiguous_a
  scenarios/
    email/
      14-non-customer-government-email.yaml
      15-non-customer-supplier-uplift-email.yaml
      16-non-customer-sales-outreach-email.yaml
      17-non-customer-named-recipient-email.yaml
      18-non-customer-general-fallback-email.yaml
      19-email-verified-customer-email.yaml
      20-email-unmatched-zero-disclosure-email.yaml
      21-email-non-customer-general-email.yaml
      22-email-ambiguous-match-disambiguation-email.yaml
      23-email-alternate-address-rejected-email.yaml
```

## Supporting ADRs

| ADR | Topic |
|-----|-------|
| 0122 | Independent email files under `eval/scenarios/email/` |
| 0123 | Email identity presets in `base.yaml` |
| 0124 | Inbound turn string or object structure |
| 0125 | Email disclosure and behavioral assertion extensions |

ADR-0072, ADR-0119, ADR-0121, and ADR-0076 were updated to reference the email batch.

## Scenario mapping

| Id | Email file | SMS parallel or purpose |
|----|------------|-------------------------|
| 14 | `14-non-customer-government-email.yaml` | SMS 14 government urgent |
| 15 | `15-non-customer-supplier-uplift-email.yaml` | SMS 15 supplier uplift |
| 16 | `16-non-customer-sales-outreach-email.yaml` | SMS 16 sales outreach |
| 17 | `17-non-customer-named-recipient-email.yaml` | SMS 17 named recipient |
| 18 | `18-non-customer-general-fallback-email.yaml` | SMS 18 general fallback |
| 19 | `19-email-verified-customer-email.yaml` | SMS 01 verified reads |
| 20 | `20-email-unmatched-zero-disclosure-email.yaml` | SMS 02 unmatched zero disclosure |
| 21 | `21-email-non-customer-general-email.yaml` | Email non-customer playbook |
| 22 | `22-email-ambiguous-match-disambiguation-email.yaml` | SMS 03 ambiguous match |
| 23 | `23-email-alternate-address-rejected-email.yaml` | SMS 05 alternate contact rejection |

## Parity transform for 14–18

Email reruns keep the same behavioral intent as their SMS counterparts and apply the email transform from ADR-0125:

- `suite: email_go_live`, `channel: email`
- `identity_preset: email_unmatched_a`
- object-form `inbound` with `body` and `subject`
- `requires_email_support_signature` and `no_sms_session_opener` on every email fixture
- `no_registered_email_recovery_script` where SMS used `no_registered_phone_script`

## Runner expectation

Run the batch with:

```bash
pnpm eval -- --suite email_go_live
```

The **Launch Eval Runner** executable remains a follow-on implementation per ADR-0121. Fixtures are the source of truth.

## Relationship to text_first_launch

`text_first_launch` and `email_go_live` are separate promotion gates. SMS go-live does not require passing `email_go_live`, and email go-live does not require scenarios 01–13 or 24–26.

**Considered options:** fold email fixtures into SMS files with dual channels (rejected in ADR-0122); deliver only 19–23 without 14–18 reruns (rejected in ADR-0051); wait for runner implementation before writing email YAML (rejected—same fixtures-first approach as ADR-0120).
