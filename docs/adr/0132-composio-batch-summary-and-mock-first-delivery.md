# Composio integration batch summary and mock-first delivery order

> **One phrase superseded by ADR-0140/0142.** The whole summary and delivery order hold.
> Under **What Composio does not replace**, "**Hermes Native Memory**" no longer names the
> store — the **Toee Business Datastore** (Postgres) is the system of record.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

This ADR closes the Composio architecture grill. It summarizes ADR-0127 through ADR-0131 and records the v1 delivery order for Text-First Launch.

## Decision summary

| Question | Decision |
|----------|----------|
| Should Hermes VA use Composio? | Yes, but only inside **Domain Adapter** implementations |
| Agent-visible tools | Unchanged Toee `toee_*` tools and v1 `action` enums |
| Which v1 tools may use Composio internally? | Layer 1 only: `toee_shopify_read`, `toee_qbo_read`, `toee_square_payment_link` |
| Which tools stay custom? | EasyRoutes, Textline, identity match shell, and all Toee-native governance tools |
| Credentials | `COMPOSIO_API_KEY` in GCP Secret Manager; OAuth via Composio Connected Accounts; runtime `COMPOSIO_USER_ID` plus per-toolkit `connected_account_id` references |
| Composio mapping | Strict one-to-one mapping per v1 `action` |
| New integrations later | ADR-first, then optional Composio behind the adapter |
| v1 implementation timing | Mock-first; Composio driver before Text-First go-live integration hardening |

## Supporting ADRs

| ADR | Topic |
|-----|-------|
| 0127 | Composio internal backend boundary |
| 0128 | Layer 1/2/3 eligibility by tool |
| 0129 | Credential and OAuth hosting |
| 0130 | One-to-one action mapping |
| 0131 | ADR-first extension workflow |

## v1 delivery order

1. Implement **Launch Eval Runner** and adapter contracts against `toee_*` mocks
2. Pass `text_first_launch` eval on mock drivers
3. Implement Layer 2 custom integrations required for SMS ingress and reads: Textline, EasyRoutes, `toee_identity_lookup`
4. Implement Layer 3 Toee-native tools: case, customer memory, knowledge, workbench, eval review
5. Add Layer 1 `composio` drivers for Shopify, QBO, and Square behind the same public actions
6. Complete Composio Connected Account onboarding per ADR-0138 and run staging integration smoke before go-live

Step 5 is not required to start steps 1–4. Step 6 is required before production Text-First Launch if Layer 1 production traffic uses Composio.

## Adapter driver layout

`packages/domain-adapters` should separate governance from backend choice:

```text
toee_shopify_read.ts
drivers/
  mock.ts
  composio.ts
  rest.ts        # optional fallback per ADR-0130
```

Default local and CI execution uses `mock`. Production Layer 1 may select `composio` through service configuration once Connected Accounts exist.

## What Composio does not replace

- **Hermes Core** orchestration and **Hermes Native Memory**
- **Tool Gate** and **Profile Tool Allowlist**
- **Channel Gateway** for Textline and future voice/email ingress
- **Launch Eval** fixture contracts
- Monorepo workbench and gateway boundaries from ADR-0091 and ADR-0099

## Architectural answer to the original question

Composio can reduce custom REST and OAuth work for standard SaaS reads and payment-link actions, but it does not replace Toee **Domain Adapter** development. Future capability expansion still begins with governed `toee_*` tool design; Composio then accelerates implementation behind that contract.

**Considered options:** adopt Composio as the primary agent tool surface (rejected in ADR-0127); defer all Composio decisions until after go-live (rejected—integration choice affects adapter layout now); implement Composio before eval mocks (rejected—fixtures-first and Runner-first delivery).
