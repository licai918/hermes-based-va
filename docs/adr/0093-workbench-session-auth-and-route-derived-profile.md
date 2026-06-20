# Workbench HttpOnly session auth with route-derived profile context

`apps/workbench` uses self-managed username and password authentication per ADR-0017 with server-side sessions rather than browser-stored bearer tokens.

## Session cookie

Successful login creates an HttpOnly session cookie, for example `workbench_session`, containing at minimum:

- `accountId`
- `username`
- `role` — `Customer Service Rep`, `Workbench Supervisor`, or `Workbench Admin`
- `lastActivityAt`

The cookie is `Secure` in production and uses an appropriate `SameSite` policy for the workbench origin. Password verification follows ADR-0018.

Logout clears the session server-side and deletes the cookie.

## Middleware protection

Next.js middleware protects:

- all `app/(authenticated)/*` pages
- all `app/api/*` routes except `/api/auth/login` and other explicit public auth endpoints

Unauthenticated requests to protected pages redirect to `/login`. Unauthenticated API requests return `401`.

Middleware and BFF handlers refresh `lastActivityAt` on authenticated activity. When inactivity exceeds the 8-hour limit from ADR-0018, the session is invalidated and the client is treated as logged out per ADR-0090.

## Route-derived active profile

v1 does not expose a manual profile switcher on one merged page. The active Hermes profile is derived from the route prefix:

| Route prefix | Active profile |
|--------------|----------------|
| `/copilot/*` and `/api/copilot/*` | `internal_copilot` |
| `/admin/*` and `/api/admin/*` | `supervisor_admin` |

BFF handlers attach both `workbenchAccount` and `activeProfile` to downstream Hermes and `packages/domain-adapters` calls. **Workbench Audit Log** entries record the active profile context per ADR-0039.

Role checks still gate navigation and APIs. **Customer Service Rep** users may access `/copilot/*` but not `/admin/*` or supervisor-only audit routes.

**Considered options:** JWT in `localStorage` (rejected—higher XSS exposure for an internal console); manual profile toggle within one session (rejected—blurs Copilot and Admin tool surfaces); infer profile only on the client (rejected—server-side tool allowlists must enforce profile boundaries).
