# Workbench App Router layout with public and authenticated route groups

`apps/workbench` uses the Next.js App Router with route groups that map directly to the v1 workbench URLs defined in ADR-0077 through ADR-0089.

## Route groups

**Public group**

- `app/(public)/login/page.tsx` → `/login`

**Authenticated group**

- `app/(authenticated)/layout.tsx` — global workbench shell from ADR-0090 and role-aware top navigation from ADR-0084
- `app/(authenticated)/copilot/page.tsx` → `/copilot`
- `app/(authenticated)/copilot/audit/auto-handled/...` → `/copilot/audit/auto-handled`
- `app/(authenticated)/copilot/audit/sales-outreach/...` → `/copilot/audit/sales-outreach`
- `app/(authenticated)/admin/knowledge/page.tsx` → `/admin/knowledge`
- `app/(authenticated)/admin/eval/page.tsx` → `/admin/eval`
- `app/(authenticated)/admin/accounts/page.tsx` → `/admin/accounts`

Route groups do not appear in the URL. The external paths remain exactly `/login`, `/copilot`, `/copilot/audit/*`, and `/admin/*`.

## BFF API routes

Workbench browser clients call Next.js BFF routes under `app/api/` rather than calling `services/hermes-gateway` directly.

Initial v1 namespaces:

- `app/api/auth/[...]`
- `app/api/copilot/[...]`
- `app/api/admin/[...]`

The authenticated layout and middleware protect `(authenticated)` pages and authenticated BFF routes together.

**Considered options:** Pages Router (rejected—older layout model and weaker nested layout support for the shared workbench shell); flat App Router tree without route groups (rejected—harder to isolate public login from authenticated shell); browser-direct calls from the workbench UI to `services/hermes-gateway` (rejected—exposes external ingress surface and complicates auth boundaries).
