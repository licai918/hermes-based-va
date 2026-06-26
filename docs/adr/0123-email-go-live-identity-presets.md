# Email go-live eval identity presets in base.yaml

Email `email_go_live` fixtures use three email-first `identity_preset` keys under `identities` in `eval/mocks/base.yaml`. They mirror the SMS preset pattern from ADR-0119 while using `from_address` as the ingress identity field for **Email Sender Match**.

## Preset keys

| Preset | Fields | Use |
|--------|--------|-----|
| `email_verified_a` | `from_address`, `shopify_customer_id`, `company_name` | Scenario 19 and other verified-email customer cases |
| `email_unmatched_a` | `from_address` | Scenarios 20–21 and email reruns of 14–18 that expect **Unmatched Caller** or **Non-Customer Contact** |
| `email_ambiguous_a` | `from_address`, `shopify_customer_ids` | Scenario 22 |

## Shared business mocks

Email presets reuse the same Shopify, QBO, and EasyRoutes records already keyed to `verified_customer_a` and ambiguous customer ids in `base.yaml`. Scenario files do not duplicate order, invoice, or delivery fixtures unless `mock_overrides` requires a delta.

`email_verified_a` uses the same `shopify_customer_id` and company as `verified_customer_a` so cross-channel eval comparisons stay aligned.

## Scenario-level overrides

Email-only ingress deltas such as a mismatched `reply_to`, alternate `from_address` for a negative test, or thread continuity ids belong in scenario `mock_overrides` or per-turn inbound metadata—not in the shared preset.

Scenario 23 uses `email_verified_a` as the authenticated **From** identity and supplies a different `reply_to` or body-supplied alternate address at the turn level to assert **Follow-up Case** creation without re-verification.

## Runner merge order

Unchanged from ADR-0119:

1. `eval/mocks/base.yaml`
2. `identity_preset` selection from `identities`
3. scenario-level `mock_overrides`

**Considered options:** reuse `verified_customer_a` and set `from_address` only in each scenario file (rejected—duplicates ingress setup across ten email fixtures); embed full inbound envelope fields in every preset (rejected—subject and thread ids vary per scenario); create separate Shopify mock trees for email (rejected—unnecessary divergence from SMS business data).
