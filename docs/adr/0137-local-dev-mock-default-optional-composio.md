# Local development mock-default with optional Composio driver

Local development and CI use mock Layer 1 integration drivers by default. Individual developers may opt into live Composio Connected Accounts for adapter integration work without changing staging or production credentials.

## Default driver

Repository local workflows default to:

```text
INTEGRATION_DRIVER=mock
```

This applies to:

- `pnpm dev:workbench`
- `pnpm dev:gateway`
- `pnpm eval` and CI **Launch Eval** runs

Mock mode does not require `COMPOSIO_API_KEY` or connected account configuration.

## Optional live Composio locally

A developer may switch one or more Layer 1 tools to the composio driver in service `.env.local` files per ADR-0098:

```text
INTEGRATION_DRIVER=composio
COMPOSIO_API_KEY=...
COMPOSIO_USER_ID=toee-local-<developer>
COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID=ca_...
COMPOSIO_QBO_CONNECTED_ACCOUNT_ID=ca_...
COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID=ca_...
```

Rules:

- each developer uses a distinct `toee-local-<developer>` Composio `user_id`
- local connected accounts must not reuse `toee-staging`, `toee-production`, or another developer's ids
- `.env.local` remains gitignored; only `.env.example` documents variable names
- local live testing should prefer read-only Layer 1 actions unless the developer has an explicit vendor sandbox tenant

## CI boundary

CI and **Launch Eval** always run with `INTEGRATION_DRIVER=mock`. CI must not load staging, production, or local Composio credentials.

## Relationship to staging

Completing a local Composio link does not replace staging onboarding from ADR-0135. Staging and production still require their own environment-specific connected accounts before go-live smoke.

**Considered options:** mock-only everywhere outside production (rejected—slows composio driver development); local dev shares staging connected accounts (rejected—violates environment isolation); local default live composio (rejected—blocks eval-first onboarding for new contributors).
