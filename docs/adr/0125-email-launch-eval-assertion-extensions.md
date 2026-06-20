# Email launch eval assertion extensions

Email `email_go_live` fixtures extend the standard assertion package from ADR-0072. They do not introduce a separate top-level `email` assertion block.

## Required email disclosure flags

Every `channel: email` scenario should set:

| Field | Meaning |
|-------|---------|
| `requires_email_support_signature` | Outbound email includes the fixed **Email Support Signature** from published **Operational Policy Knowledge** slot 6 |
| `no_sms_session_opener` | Outbound email does not use **SMS Session Opener**-style first-reply introduction language |

The runner resolves the exact signature phrase from eval policy fixtures or published slot 6 text. Scenario files declare the requirement; they do not hardcode the full signature string unless a scenario needs an extra `text.must_contain` delta.

## Additional email disclosure flags

Use when the scenario intent requires them:

| Field | Meaning | Typical scenarios |
|-------|---------|-------------------|
| `no_registered_phone_script` | No Registered Phone recovery language | 20, email reruns of 14–18 |
| `no_registered_email_recovery_script` | No "send from your registered email" or similar recovery language | 20, unmatched email customer service |
| `no_account_disclosure` | Unchanged from ADR-0072 | 20–22, email 14–18 |

## Email behavioral assertions

ADR-0072 behavioral fields still apply on email fixtures.

Scenario 23 adds:

| Field | Meaning |
|-------|---------|
| `alternate_address_not_verified` | Hermes does not treat `reply_to` or a body-supplied alternate email as a new verified sender for **Email Sender Match**, **Payment Link**, or account-scoped reads in the same turn |

Scenario 23 also expects `case_created: true` and forbids sending a payment link to the alternate address, paralleling SMS scenario 05.

## Email reruns of 14–18

Email copies of scenarios 14–18 keep the same behavioral intent as their SMS counterparts:

- same `contact_reason`, `case_urgency`, and `case_created` expectations where applicable
- email disclosure flags instead of SMS-only opener checks
- `text.must_not_contain` updated to block Registered Email recovery language where relevant, while keeping zero-account-disclosure checks

## Minimum package unchanged

Each email scenario still needs at minimum:

1. one behavioral or tool assertion
2. one disclosure or text assertion
3. `max_severity`

**Considered options:** a separate `assertions.email` block (rejected—splits runner logic); signature checks only through manual `must_contain` per file (rejected—brittle when slot 6 text changes); skip `no_sms_session_opener` because email never uses SMS openers (rejected—explicit assertion catches channel regression).
