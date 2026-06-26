# Launch eval identity presets and scenario file naming

Launch eval scenario fixtures use stable `identity_preset` keys from `eval/mocks/base.yaml` and a numbered kebab-case file naming convention.

## identity_preset keys

SMS `text_first_launch` scenarios reference keys under `identities` in `eval/mocks/base.yaml`:

| Preset | Use |
|--------|-----|
| `verified_customer_a` | Verified customer SMS scenarios such as 01, 04, 05, and 09–13 |
| `unmatched_phone` | Unmatched caller SMS scenarios such as 02 and most 14–18 cases |
| `ambiguous_phone` | Ambiguous phone-match scenarios such as 03 |

Email `email_go_live` scenarios reference these keys:

| Preset | Use |
|--------|-----|
| `email_verified_a` | Verified sender email scenarios such as 19 |
| `email_unmatched_a` | Unmatched or non-customer email scenarios such as 20–21 and email reruns of 14–18 |
| `email_ambiguous_a` | Ambiguous email-match scenario 22 |

Email preset fields are defined in ADR-0123. Email fixture files live under `eval/scenarios/email/` per ADR-0122.

**Customer Memory** scenarios 24–26 use `verified_customer_a` or `unmatched_phone` according to the case being tested.

Scenario files set `identity_preset` and use `mock_overrides` only for deltas from the shared baseline.

## File naming

Scenario files live under `eval/scenarios/` and use this filename pattern:

```text
{id}-{kebab-slug}.yaml
```

Examples:

- `01-verified-order-delivery-ar.yaml`
- `14-non-customer-government.yaml`
- `24-customer-memory-explicit-upsert.yaml`
- `email/19-email-verified-customer-email.yaml`

Email files use `email/{id}-{kebab-slug}-email.yaml` per ADR-0122.

`scenario_id` inside the file must match the numeric id prefix in the filename.

## Runner merge order

The **Launch Eval Runner** resolves identity and business mocks in this order:

1. `eval/mocks/base.yaml`
2. `identity_preset` selection from `identities`
3. scenario-level `mock_overrides`

**Considered options:** inline full identity mocks per scenario file (rejected—duplicate fixture data); arbitrary filenames without numeric ids (rejected—harder to run targeted suites); reuse SMS phone presets for email scenarios (rejected—email ingress differs).
