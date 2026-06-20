# Ops-side Composio Connected Account onboarding without Workbench UI

v1 Composio Connected Account onboarding is an infrastructure operation performed outside the **Admin Governance Console**. It does not add a fourth admin route or a workbench OAuth UI in Text-First Launch.

## Who performs onboarding

**Workbench Supervisor** or **Workbench Admin** users with infrastructure access, or delegated DevOps, complete onboarding through:

- Composio Dashboard, or
- the `composio` CLI and repository ops runbook

Customer-facing Hermes channels, **Copilot Workbench**, and day-to-day **Admin Governance Console** routes do not initiate vendor OAuth.

## v1 admin surface unchanged

The **Admin Governance Console** remains three routes per ADR-0078:

- `/admin/knowledge`
- `/admin/eval`
- `/admin/accounts`

Composio connection status, reconnect, and OAuth redirects are out of scope for v1 workbench UI. A future `/admin/integrations` route would require a new ADR, a new governed admin tool, and explicit OAuth callback design.

## Composio v3 identity model

Tooe Tire uses Composio v3 terminology:

| Concept | v1 value |
|---------|----------|
| `user_id` | one fixed id per deployment environment, such as `toee-production` or `toee-staging` |
| `connected_account_id` | one active connected account per Layer 1 toolkit in that environment |
| `auth_config_id` | Composio auth config reference for each toolkit, recorded in ops runbook |

Legacy Composio terms such as `entity ID` map to `user_id` plus toolkit-specific `connected_account_id` values, not a single entity reference per adapter.

## Onboarding sequence

1. Ensure `COMPOSIO_API_KEY` is present in the target environment per ADR-0129.
2. Create or verify Composio auth configs for Shopify, QuickBooks, and Square.
3. Run `connected_accounts.link(user_id, auth_config_id)` for each toolkit and complete vendor OAuth consent.
4. Record the returned `connected_account_id` for each toolkit in environment configuration.
5. Deploy or update Cloud Run env for services that execute Layer 1 adapters.
6. Run staging smoke against governed `toee_*` actions before production Text-First Launch.

Reconnection after token revocation or vendor password changes repeats steps 3–6 for the affected toolkit only.

## Environment separation

Production and staging use different `user_id` values and different `connected_account_id` values. Production Connected Accounts must not be reused in staging eval or developer experiments.

## Documentation

The step-by-step CLI and dashboard commands live in [docs/ops/composio-connected-accounts.md](../../ops/composio-connected-accounts.md). v1 does not depend on workbench product UI for those steps.

**Considered options:** add `/admin/integrations` in v1 (rejected—expands admin surface, OAuth callback scope, and BFF work without Text-First Launch need); rely on in-chat Composio connection meta-tools (rejected—wrong audience and violates adapter boundary); auto-connect during local `pnpm dev` (rejected—non-deterministic developer setup and credential leakage risk).
