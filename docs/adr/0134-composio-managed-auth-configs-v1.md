# Composio-managed auth configs for v1 Layer 1 toolkits

v1 Composio Connected Account onboarding uses Composio-managed auth configs for all Layer 1 toolkits: Shopify, QuickBooks, and Square.

## v1 choice

Each toolkit connects through a Composio default auth config created or verified in the Composio Dashboard. Toee Tire does not register custom vendor OAuth applications in v1 Text-First Launch onboarding.

Onboarding uses Composio v3 `connected_accounts.link(user_id, auth_config_id)` for these Composio-managed configs. The deprecated `initiate()` path is not used for new v1 setup.

## Ops runbook references

The ops runbook is [docs/ops/composio-connected-accounts.md](../../ops/composio-connected-accounts.md). It records non-secret auth config ids per toolkit, for example:

- `COMPOSIO_SHOPIFY_AUTH_CONFIG_ID`
- `COMPOSIO_QBO_AUTH_CONFIG_ID`
- `COMPOSIO_SQUARE_AUTH_CONFIG_ID`

These values are used only during link and reconnect procedures. Runtime adapter calls use `COMPOSIO_USER_ID` and per-toolkit `connected_account_id` values per ADR-0129.

## Branding and audience

OAuth consent screens may display Composio-managed branding. That is acceptable in v1 because Connected Account onboarding is an internal ops action performed by authorized Toee staff, not a customer-facing Hermes channel flow.

## Future custom auth configs

A later ADR may move one or more toolkits to custom auth configs with Toee-owned OAuth apps when compliance, vendor app review, or white-label consent branding requires it.

Migration steps for a toolkit are:

1. create the custom auth config in Composio
2. run a new `connected_accounts.link()` against the new `auth_config_id`
3. update the toolkit `connected_account_id` in environment configuration
4. rerun staging smoke for the affected `toee_*` actions

The public Toee tool contract does not change during that migration.

**Considered options:** custom OAuth apps for all toolkits in v1 (rejected—slower onboarding without Text-First Launch benefit); mixed managed and custom without a documented migration path (rejected—ops ambiguity); customer-facing workbench OAuth branding controls (rejected—ADR-0133 keeps onboarding ops-side).
